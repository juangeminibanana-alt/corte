package app.creatorhub

import java.io.IOException
import java.io.InputStream

internal object NativeExitTrace {
    private const val MAX_TRACE_BYTES = 4 * 1024 * 1024
    private const val MAX_FRAMES = 6

    // Wire tags from AOSP debuggerd/proto/tombstone.proto.
    private const val TOMBSTONE_PID = 5 shl 3
    private const val TOMBSTONE_TID = 6 shl 3
    private const val TOMBSTONE_THREADS = (16 shl 3) or 2
    private const val MAP_KEY = 1 shl 3
    private const val MAP_VALUE = (2 shl 3) or 2
    private const val THREAD_BACKTRACE = (4 shl 3) or 2
    private const val FRAME_RELATIVE_PC = 1 shl 3
    private const val FRAME_FILE_NAME = (6 shl 3) or 2
    private const val FRAME_BUILD_ID = (8 shl 3) or 2
    private val libraryName = Regex("[a-zA-Z0-9_.+\\-]{1,96}\\.so")
    private val elfBuildId = Regex("(?:[a-fA-F0-9]{2}){1,64}")

    data class Frame(val library: String, val relativePc: ULong, val buildId: String?)

    fun read(input: InputStream, expectedPid: Int): List<Frame> = try {
        val bytes = ByteArray(MAX_TRACE_BYTES)
        val size = readBounded(input, bytes)
        parse(bytes, size, expectedPid)
    } catch (_: IOException) {
        emptyList()
    } catch (_: IllegalArgumentException) {
        emptyList()
    }

    private fun readBounded(input: InputStream, bytes: ByteArray): Int {
        var size = 0
        while (size < bytes.size) {
            val read = input.read(bytes, size, bytes.size - size)
            if (read < 0) return size
            require(read > 0)
            size += read
        }
        require(input.read() == -1)
        return size
    }

    private fun parse(bytes: ByteArray, size: Int, expectedPid: Int): List<Frame> {
        var pid = 0L
        var crashingTid = 0L
        Message(bytes, 0, size).fields { tag ->
            when (tag) {
                TOMBSTONE_PID -> pid = varint()
                TOMBSTONE_TID -> crashingTid = varint()
            }
        }
        if (pid != expectedPid.toLong() || crashingTid !in 1..Int.MAX_VALUE.toLong()) {
            return emptyList()
        }

        // Protobuf fields can appear in any order. Read the process identity first
        // and inspect only the matching thread's frames in the second pass.
        var backtrace: List<Frame>? = null
        Message(bytes, 0, size).fields { tag ->
            if (tag == TOMBSTONE_THREADS && backtrace == null) {
                var threadId = 0L
                var thread: Message? = null
                message().fields { entryTag ->
                    when (entryTag) {
                        MAP_KEY -> threadId = varint()
                        MAP_VALUE -> thread = message()
                    }
                }
                if (threadId == crashingTid) backtrace = thread?.frames()
            }
        }
        return backtrace.orEmpty()
    }

    private fun Message.frames(): List<Frame> = buildList {
        var framesRead = 0
        fields { tag ->
            if (tag == THREAD_BACKTRACE && framesRead < MAX_FRAMES) {
                framesRead++
                message().frame()?.let(::add)
            }
        }
    }

    private fun Message.frame(): Frame? {
        var relativePc = 0uL
        var library: String? = null
        var buildId: String? = null
        fields { tag ->
            when (tag) {
                FRAME_RELATIVE_PC -> relativePc = varint().toULong()
                FRAME_FILE_NAME -> library = string(512)
                    ?.removeSuffix(" (deleted)")
                    ?.substringAfterLast('/')
                    ?.substringAfterLast('!')
                    ?.takeIf(libraryName::matches)
                FRAME_BUILD_ID -> buildId = string(128)?.takeIf(elfBuildId::matches)
            }
        }
        return library?.let { Frame(it, relativePc, buildId) }
    }

    private class Message(private val bytes: ByteArray, private var offset: Int, private val end: Int) {
        fun fields(visit: Message.(Int) -> Unit) {
            while (offset < end) {
                val tag = varint()
                require(tag in 8..0xffff_ffffL)
                val start = offset
                visit(tag.toInt())
                if (offset == start) {
                    when (tag.toInt() and 7) {
                        0 -> varint()
                        1 -> consume(8)
                        2 -> consume(length())
                        5 -> consume(4)
                        else -> throw IllegalArgumentException("Unsupported protobuf wire type")
                    }
                }
            }
        }

        fun varint(): Long {
            var result = 0L
            for (shift in 0..63 step 7) {
                val byte = bytes[consume(1)].toInt() and 0xff
                require(shift < 63 || byte <= 1)
                result = result or ((byte and 0x7f).toLong() shl shift)
                if (byte < 0x80) return result
            }
            throw IllegalArgumentException("Invalid protobuf varint")
        }

        fun message(): Message {
            val length = length()
            val start = consume(length)
            return Message(bytes, start, offset)
        }

        fun string(maxBytes: Int): String? {
            val length = length()
            val start = consume(length)
            return if (length <= maxBytes) String(bytes, start, length, Charsets.UTF_8) else null
        }

        private fun length(): Int {
            val size = varint()
            require(size in 0L..(end - offset).toLong())
            return size.toInt()
        }

        private fun consume(length: Int): Int {
            require(length in 0..(end - offset))
            val start = offset
            offset += length
            return start
        }
    }
}
