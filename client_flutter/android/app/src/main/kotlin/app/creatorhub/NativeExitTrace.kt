package app.creatorhub

import java.io.IOException
import java.io.InputStream

internal object NativeExitTrace {
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
    private const val FRAME_FILE_MAP_OFFSET = 7 shl 3
    private const val FRAME_BUILD_ID = (8 shl 3) or 2
    private val libraryName = Regex("[a-zA-Z0-9_.+@-]{1,96}\\.(?:so|apk)")
    private val elfBuildId = Regex("(?:[a-fA-F0-9]{2}){1,64}")

    data class Frame(
        val index: Int,
        val library: String?,
        val relativePc: ULong,
        val fileMapOffset: ULong,
        val buildId: String?,
    )

    fun read(input: InputStream, expectedPid: Int): List<Frame> = try {
        require(expectedPid > 0)
        WireReader(input.buffered()).parse(expectedPid)
    } catch (_: IOException) {
        emptyList()
    } catch (_: IllegalArgumentException) {
        emptyList()
    }

    private fun WireReader.parse(expectedPid: Int): List<Frame> {
        var pid = 0L
        var crashingTid: Long? = null
        var backtrace = emptyList<Frame>()
        // Protobuf fields can appear in any order. Keep only frame summaries
        // if thread entries arrive before the crashing thread ID.
        val pending = mutableMapOf<Long, List<Frame>>()
        fields { tag ->
            when (tag) {
                TOMBSTONE_PID -> {
                    val reportedPid = varint()
                    require(pid == 0L || pid == reportedPid)
                    pid = reportedPid
                }
                TOMBSTONE_TID -> {
                    val tid = varint()
                    require(tid in 1..Int.MAX_VALUE.toLong())
                    require(crashingTid == null || crashingTid == tid)
                    if (crashingTid == null) {
                        crashingTid = tid
                        backtrace = pending[tid].orEmpty()
                        pending.clear()
                    }
                }
                TOMBSTONE_THREADS -> {
                    val (threadId, frames) = message { thread(crashingTid) }
                    if (threadId == crashingTid) {
                        backtrace = frames
                    } else if (crashingTid == null && threadId > 0) {
                        if (frames.isEmpty()) pending.remove(threadId)
                        else pending[threadId] = frames
                    }
                }
            }
        }
        return if (pid == expectedPid.toLong() && crashingTid != null) backtrace else emptyList()
    }

    private fun WireReader.thread(crashingTid: Long?): Pair<Long, List<Frame>> {
        var threadId: Long? = null
        var backtrace = emptyList<Frame>()
        fields { tag ->
            when (tag) {
                MAP_KEY -> {
                    val key = varint()
                    require(threadId == null || threadId == key)
                    threadId = key
                }
                MAP_VALUE -> if (threadId == null || crashingTid == null || threadId == crashingTid) {
                    backtrace = message { frames() }
                }
            }
        }
        return (threadId ?: 0L) to backtrace
    }

    private fun WireReader.frames(): List<Frame> = buildList {
        fields { tag ->
            if (tag == THREAD_BACKTRACE && size < MAX_FRAMES) {
                add(message { frame(size) })
            }
        }
    }

    private fun WireReader.frame(index: Int): Frame {
        var relativePc = 0uL
        var fileMapOffset = 0uL
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
                FRAME_FILE_MAP_OFFSET -> fileMapOffset = varint().toULong()
                FRAME_BUILD_ID -> buildId = string(128)?.takeIf(elfBuildId::matches)
            }
        }
        return Frame(index, library, relativePc, fileMapOffset, buildId)
    }

    private class WireReader(private val input: InputStream) {
        private var position = 0L
        private var limit = Long.MAX_VALUE

        fun fields(visit: (Int) -> Unit) {
            while (position < limit) {
                val first = input.read()
                if (first < 0) {
                    require(limit == Long.MAX_VALUE)
                    return
                }
                position++
                val tag = varint(first)
                require(tag in 8..0xffff_ffffL)
                val start = position
                visit(tag.toInt())
                if (position == start) {
                    when (tag.toInt() and 7) {
                        0 -> varint()
                        1 -> skip(8)
                        2 -> skip(length())
                        5 -> skip(4)
                        else -> throw IllegalArgumentException("Unsupported protobuf wire type")
                    }
                }
            }
        }

        fun varint(first: Int = readByte()): Long {
            var result = (first and 0x7f).toLong()
            if (first < 0x80) return result
            for (shift in 7..63 step 7) {
                val byte = readByte()
                require(shift < 63 || byte <= 1)
                result = result or ((byte and 0x7f).toLong() shl shift)
                if (byte < 0x80) return result
            }
            throw IllegalArgumentException("Invalid protobuf varint")
        }

        fun <T> message(visit: () -> T): T {
            val size = length()
            val parentLimit = limit
            limit = position + size
            return try {
                visit().also { require(position == limit) }
            } finally {
                limit = parentLimit
            }
        }

        fun string(maxBytes: Int): String? {
            val size = length()
            if (size > maxBytes) {
                skip(size)
                return null
            }
            return String(ByteArray(size.toInt()) { readByte().toByte() }, Charsets.UTF_8)
        }

        private fun length(): Long {
            val size = varint()
            require(size in 0L..minOf(Int.MAX_VALUE.toLong(), limit - position))
            return size
        }

        private fun readByte(): Int {
            require(position < limit)
            val byte = input.read()
            require(byte >= 0)
            position++
            return byte
        }

        private fun skip(size: Long) {
            require(size in 0L..(limit - position))
            val end = position + size
            while (position < end - 1) {
                val skipped = input.skip(end - position - 1)
                if (skipped > 0) position += skipped else readByte()
            }
            // Some streams seek past EOF, so also check the final skipped byte.
            if (position < end) readByte()
        }
    }
}
