package app.creatorhub

import java.io.ByteArrayOutputStream

/** Standalone JVM regressions using synthetic protobuf traces. */
fun main() {
    val pid = number(5, 410uL)
    val tid = number(6, 920uL)
    val otherThread = thread(919uL, frame("/another/path/libother.so", 0x111uL))
    val crashThread = thread(
        920uL,
        frame("/private/session/base.apk", 0x12auL, 0x8000uL, "a1b2"),
        frame("/private/session/android.hardware.graphics.mapper@4.0-impl.so", 0x22auL),
        frame("[anon:dalvik-jit-code-cache]", ULong.MAX_VALUE, buildId = "f0e1"),
        frame("/private/session/base.apk!libflutter.so (deleted)", 0x42auL),
        frame("/private/session/hidden.odex", 0x52auL, buildId = "bad/path"),
        frame(null, 0x62auL),
        frame("/private/session/libseventh.so", 0x72auL),
    )
    val expected = listOf(
        NativeExitTrace.Frame(0, "base.apk", 0x12auL, 0x8000uL, "a1b2"),
        NativeExitTrace.Frame(1, "android.hardware.graphics.mapper@4.0-impl.so", 0x22auL, 0uL, null),
        NativeExitTrace.Frame(2, null, ULong.MAX_VALUE, 0uL, "f0e1"),
        NativeExitTrace.Frame(3, "libflutter.so", 0x42auL, 0uL, null),
        NativeExitTrace.Frame(4, null, 0x52auL, 0uL, null),
        NativeExitTrace.Frame(5, null, 0x62auL, 0uL, null),
    )
    val valid = pid + tid + otherThread + crashThread
    check(read(valid) == expected)
    check(read(valid, expectedPid = 411).isEmpty())
    check(read(pid + number(6, 999uL) + otherThread + crashThread).isEmpty())
    check(read(valid + number(5, 411uL)).isEmpty())

    val padding = bytes(17, ByteArray(5 * 1024 * 1024))
    // Protobuf permits the thread map and its key to follow their values.
    check(read(otherThread + crashThread + padding + tid + pid) == expected)
    check(read(pid + tid + padding + otherThread + crashThread) == expected)
    check(read(valid + padding.copyOf(padding.size - 1)).isEmpty())
    check(read(valid.copyOf(valid.size - 1)).isEmpty())
    println("PASS: native trace order, redaction, identity, large streams and truncation")
}

private fun read(trace: ByteArray, expectedPid: Int = 410) =
    NativeExitTrace.read(trace.inputStream(), expectedPid)

private fun thread(tid: ULong, vararg frames: ByteArray): ByteArray =
    bytes(16, bytes(2, frames.fold(byteArrayOf(), ByteArray::plus)) + number(1, tid))

private fun frame(
    path: String?,
    relativePc: ULong,
    fileOffset: ULong = 0uL,
    buildId: String? = null,
): ByteArray {
    val contents = number(1, relativePc) + number(7, fileOffset) +
        (path?.let { bytes(6, it.toByteArray()) } ?: byteArrayOf()) +
        (buildId?.let { bytes(8, it.toByteArray()) } ?: byteArrayOf())
    return bytes(4, contents)
}

private fun number(field: Int, value: ULong): ByteArray =
    varint((field shl 3).toULong()) + varint(value)

private fun bytes(field: Int, value: ByteArray): ByteArray =
    varint(((field shl 3) or 2).toULong()) + varint(value.size.toULong()) + value

private fun varint(value: ULong): ByteArray {
    val bytes = ByteArrayOutputStream()
    var remaining = value
    while (remaining >= 0x80uL) {
        bytes.write((remaining and 0x7fuL).toInt() or 0x80)
        remaining = remaining shr 7
    }
    bytes.write(remaining.toInt())
    return bytes.toByteArray()
}
