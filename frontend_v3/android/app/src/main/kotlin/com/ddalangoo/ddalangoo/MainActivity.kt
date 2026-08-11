package com.ddalangoo.ddalangoo

import android.Manifest
import android.app.ActivityManager
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.app.ActivityCompat
import com.ddalangoo.ddalangoo.accessibility.AutomationContract
import com.ddalangoo.ddalangoo.accessibility.AutomationLogger
import com.ddalangoo.ddalangoo.accessibility.AutomationTask
import com.ddalangoo.ddalangoo.accessibility.AutomationTaskStore
import com.ddalangoo.ddalangoo.accessibility.DdalangooAccessibilityService
import com.ddalangoo.ddalangoo.accessibility.PurchaseHistoryExtractionStore
import com.ddalangoo.ddalangoo.accessibility.SearchInspectionStore
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.sqrt

class MainActivity : FlutterActivity() {
    private val pcmMethodChannelName = "com.ddalangoo.ddalangoo/native_pcm_recording"
    private val pcmEventChannelName = "com.ddalangoo.ddalangoo/native_pcm_recording/events"
    private val speechMethodChannelName = "com.ddalangoo.ddalangoo/native_speech_recognition"
    private val speechEventChannelName =
        "com.ddalangoo.ddalangoo/native_speech_recognition/events"

    private val mainHandler = Handler(Looper.getMainLooper())
    private var pcmEventSink: EventChannel.EventSink? = null
    private var speechEventSink: EventChannel.EventSink? = null
    private var pcmRecorder: NativePcmRecorder? = null
    private var speechSession: NativeSpeechRecognizerSession? = null

    private data class ShoppingPlatformApp(
        val platform: String,
        val displayName: String,
        val packageName: String,
    )

    private val supportedShoppingPlatforms = listOf(
        ShoppingPlatformApp("naver", "네이버", "com.nhn.android.search"),
        ShoppingPlatformApp("coupang", "쿠팡", "com.coupang.mobile"),
        ShoppingPlatformApp("kurly", "컬리", "com.dbs.kurly.m2"),
        ShoppingPlatformApp("gmarket", "지마켓", "com.ebay.kr.gmarket"),
        ShoppingPlatformApp("hyundaihomeshopping", "현대홈쇼핑", "com.hmallapp"),
    )

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        setupAccessibilityAutomationChannel(flutterEngine)

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            pcmMethodChannelName,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "isAvailable" -> {
                    result.success(
                        AudioRecord.getMinBufferSize(
                            SAMPLE_RATE,
                            CHANNEL_CONFIG,
                            AUDIO_FORMAT,
                        ) > 0,
                    )
                }

                "startRecording" -> {
                    val path = call.argument<String>("path")
                    if (path.isNullOrBlank()) {
                        result.error("missing_path", "Recording path is required.", null)
                        return@setMethodCallHandler
                    }
                    if (!hasRecordAudioPermission()) {
                        result.error(
                            "missing_permission",
                            "RECORD_AUDIO permission is required.",
                            null,
                        )
                        return@setMethodCallHandler
                    }
                    try {
                        pcmRecorder?.cancel()
                        pcmRecorder = NativePcmRecorder(
                            path = path,
                            onRms = { rmsDb ->
                                emitPcmEvent(mapOf("type" to "rms", "currentDb" to rmsDb))
                            },
                            onError = { code, message ->
                                emitPcmEvent(
                                    mapOf(
                                        "type" to "error",
                                        "code" to code,
                                        "message" to message,
                                    ),
                                )
                            },
                        ).also { it.start() }
                        result.success(null)
                    } catch (error: Exception) {
                        result.error("start_failed", error.message, null)
                    }
                }

                "stopRecording" -> {
                    try {
                        val path = pcmRecorder?.stop()
                        pcmRecorder = null
                        result.success(path)
                    } catch (error: Exception) {
                        result.error("stop_failed", error.message, null)
                    }
                }

                "cancelRecording" -> {
                    pcmRecorder?.cancel()
                    pcmRecorder = null
                    result.success(null)
                }

                else -> result.notImplemented()
            }
        }

        EventChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            pcmEventChannelName,
        ).setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, sink: EventChannel.EventSink) {
                pcmEventSink = sink
            }

            override fun onCancel(arguments: Any?) {
                pcmEventSink = null
            }
        })

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            speechMethodChannelName,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "isAvailable" -> {
                    result.success(SpeechRecognizer.isRecognitionAvailable(this))
                }

                "startListening" -> {
                    if (!hasRecordAudioPermission()) {
                        result.error(
                            "missing_permission",
                            "RECORD_AUDIO permission is required.",
                            null,
                        )
                        return@setMethodCallHandler
                    }
                    if (!SpeechRecognizer.isRecognitionAvailable(this)) {
                        result.error(
                            "speech_unavailable",
                            "SpeechRecognizer is not available on this device.",
                            null,
                        )
                        return@setMethodCallHandler
                    }

                    val locale = call.argument<String>("locale") ?: Locale.getDefault().toLanguageTag()
                    val requestId = call.argument<String>("requestId")
                    try {
                        speechSession?.cancel()
                        speechSession = NativeSpeechRecognizerSession(
                            activity = this,
                            requestId = requestId ?: "native_asr_${System.currentTimeMillis()}",
                            onEvent = { event -> emitSpeechEvent(event) },
                        )
                        val pendingSession = speechSession
                        mainHandler.postDelayed({
                            pendingSession?.start(locale = locale)
                        }, TTS_TO_STT_ECHO_SETTLE_MS)
                        result.success(null)
                    } catch (error: Exception) {
                        result.error("start_failed", error.message, null)
                    }
                }

                "stopListening" -> {
                    speechSession?.stop()
                    result.success(null)
                }

                "cancelListening" -> {
                    speechSession?.cancel()
                    speechSession = null
                    result.success(null)
                }

                else -> result.notImplemented()
            }
        }

        EventChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            speechEventChannelName,
        ).setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, sink: EventChannel.EventSink) {
                speechEventSink = sink
            }

            override fun onCancel(arguments: Any?) {
                speechEventSink = null
            }
        })
    }

    private fun setupAccessibilityAutomationChannel(flutterEngine: FlutterEngine) {
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            AutomationContract.CHANNEL_NAME,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                AutomationContract.Method.SET_TASK,
                AutomationContract.Method.SET_TEST_TASK -> {
                    val arguments = call.arguments as? Map<*, *> ?: emptyMap<String, Any?>()
                    val task = AutomationTask.fromMap(
                        arguments.entries.associate { (key, value) -> key.toString() to value },
                    )
                    AutomationTaskStore.setTask(task)
                    if (shouldLaunchPackageForTask(task)) {
                        task.effectivePackageName()?.let { packageName ->
                            launchPackage(packageName)
                        }
                    }
                    DdalangooAccessibilityService.scheduleTaskStartedTicks()
                    result.success(true)
                }

                AutomationContract.Method.LAUNCH_PLATFORM_APP -> {
                    val packageName = call.argument<String>(AutomationContract.Argument.PACKAGE_NAME)
                    result.success(packageName?.let { launchPackage(it) } ?: false)
                }

                AutomationContract.Method.CLEAR_TASK -> {
                    AutomationTaskStore.clearTask()
                    result.success(true)
                }

                AutomationContract.Method.GET_STATUS -> {
                    result.success(AutomationTaskStore.statusMap())
                }

                AutomationContract.Method.CONSUME_RESULT -> {
                    result.success(AutomationTaskStore.consumeResultMap())
                }

                AutomationContract.Method.GET_INSTALLED_SHOPPING_PLATFORMS -> {
                    result.success(getInstalledShoppingPlatforms())
                }

                AutomationContract.Method.GET_ACCUMULATED_PURCHASE_HISTORY_RESULT -> {
                    result.success(PurchaseHistoryExtractionStore.accumulatedCandidatesJson())
                }

                AutomationContract.Method.GET_SEARCH_INSPECTION_RESULT -> {
                    result.success(SearchInspectionStore.resultJson())
                }

                AutomationContract.Method.CLEAR_PURCHASE_HISTORY_RESULT -> {
                    PurchaseHistoryExtractionStore.clear()
                    result.success(true)
                }

                AutomationContract.Method.CLEAR_SEARCH_INSPECTION_RESULT -> {
                    SearchInspectionStore.clear()
                    result.success(true)
                }

                AutomationContract.Method.DUMP_CURRENT_UI_TREE -> {
                    AutomationLogger.info(
                        "dumpCurrentUiTree requested. Trigger a screen event to collect the current UI tree.",
                    )
                    result.success(true)
                }

                else -> result.notImplemented()
            }
        }
    }

    private fun launchPackage(packageName: String): Boolean {
        if (packageName == this.packageName) {
            return bringDdalangooTaskToFront()
        }

        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        if (launchIntent == null) {
            AutomationLogger.warn("launch failed packageName=$packageName reason=launchIntent_missing")
            return false
        }

        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(launchIntent)
        AutomationLogger.info("launch requested packageName=$packageName")
        return true
    }

    private fun bringDdalangooTaskToFront(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            val activityManager = getSystemService(ActivityManager::class.java)
            val appTask = activityManager?.appTasks?.firstOrNull()
            if (appTask != null) {
                appTask.moveToFront()
                AutomationLogger.info("bring own task to front packageName=$packageName")
                return true
            }
        }

        val ownIntent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        startActivity(ownIntent)
        AutomationLogger.info("bring own activity to front fallback packageName=$packageName")
        return true
    }

    private fun getInstalledShoppingPlatforms(): List<Map<String, Any>> {
        return supportedShoppingPlatforms.map { platform ->
            mapOf(
                "platform" to platform.platform,
                "displayName" to platform.displayName,
                "packageName" to platform.packageName,
                "isInstalled" to isPackageInstalled(platform.packageName),
            )
        }
    }

    private fun isPackageInstalled(packageName: String): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                packageManager.getPackageInfo(
                    packageName,
                    PackageManager.PackageInfoFlags.of(0),
                )
            } else {
                @Suppress("DEPRECATION")
                packageManager.getPackageInfo(packageName, 0)
            }
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }
    }

    private fun shouldLaunchPackageForTask(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.OPEN_MY_KURLY ||
            task.currentStep == AutomationContract.Step.OPEN_MY_COUPANG ||
            task.currentStep == AutomationContract.Step.OPEN_SEARCH ||
            task.taskType == AutomationContract.TaskType.INSPECT_SEARCH_FLOW
    }

    override fun onDestroy() {
        pcmRecorder?.cancel()
        pcmRecorder = null
        speechSession?.cancel()
        speechSession = null
        super.onDestroy()
    }

    private fun emitPcmEvent(event: Map<String, Any>) {
        mainHandler.post {
            pcmEventSink?.success(event)
        }
    }

    private fun emitSpeechEvent(event: Map<String, Any>) {
        mainHandler.post {
            speechEventSink?.success(event)
        }
    }

    private fun hasRecordAudioPermission(): Boolean {
        return ActivityCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private class NativeSpeechRecognizerSession(
        private val activity: FlutterActivity,
        private val requestId: String,
        private val onEvent: (Map<String, Any>) -> Unit,
    ) : RecognitionListener {
        private val handler = Handler(Looper.getMainLooper())
        private var speechRecognizer: SpeechRecognizer? = null
        private var latestPartial = ""
        private var stopRequested = false
        private var activeLocale: String = Locale.getDefault().toLanguageTag()
        private var consecutiveRecoverableErrors = 0
        private var pendingRestart: Runnable? = null

        fun start(locale: String) {
            cancel()
            activeLocale = locale
            stopRequested = false
            latestPartial = ""
            consecutiveRecoverableErrors = 0
            startRecognizer(resetPartial = false)
        }

        fun stop() {
            stopRequested = true
            cancelPendingRestart()
            emitEvent(mapOf("type" to "state", "value" to "stop_requested"))
            speechRecognizer?.stopListening()
        }

        fun cancel() {
            stopRequested = false
            cancelPendingRestart()
            runCatching { speechRecognizer?.cancel() }
            destroyRecognizer()
        }

        override fun onReadyForSpeech(params: Bundle?) {
            emitEvent(mapOf("type" to "state", "value" to "ready"))
        }

        override fun onBeginningOfSpeech() {
            emitEvent(mapOf("type" to "state", "value" to "speech_begin"))
        }

        override fun onRmsChanged(rmsdB: Float) {
            val mappedDb = (rmsdB.toDouble() - 12.0).coerceIn(MIN_DB, 0.0)
            emitEvent(mapOf("type" to "rms", "currentDb" to mappedDb))
        }

        override fun onBufferReceived(buffer: ByteArray?) = Unit

        override fun onEndOfSpeech() {
            emitEvent(mapOf("type" to "state", "value" to "speech_end"))
        }

        override fun onError(error: Int) {
            val code = speechErrorCode(error)
            val message = when (error) {
                SpeechRecognizer.ERROR_AUDIO -> "Audio recording error."
                SpeechRecognizer.ERROR_CLIENT -> "Client side error."
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Insufficient permissions."
                SpeechRecognizer.ERROR_NETWORK -> "Network error."
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout."
                SpeechRecognizer.ERROR_NO_MATCH -> "No recognition match."
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy."
                SpeechRecognizer.ERROR_SERVER -> "Recognition server error."
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Speech timeout."
                else -> "Speech recognition failed."
            }

            val hasPartialTranscript = latestPartial.isNotBlank()
            val recoverable =
                !stopRequested &&
                    !hasPartialTranscript &&
                    (
                        error == SpeechRecognizer.ERROR_NO_MATCH ||
                            error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                        ) &&
                    consecutiveRecoverableErrors < MAX_RECOVERABLE_ERRORS

            if (!stopRequested && hasPartialTranscript) {
                emitEvent(
                    mapOf(
                        "type" to "result",
                        "text" to latestPartial,
                        "source" to "partial_fallback",
                    ),
                )
                destroyRecognizer()
                return
            }

            emitEvent(
                mapOf(
                    "type" to "error",
                    "code" to code,
                    "message" to message,
                    "latestPartial" to latestPartial,
                    "stopRequested" to stopRequested,
                    "recoverable" to recoverable,
                ),
            )

            if (recoverable) {
                consecutiveRecoverableErrors += 1
                scheduleRestart()
                return
            }

            destroyRecognizer()
        }

        override fun onResults(results: Bundle?) {
            val transcript = extractTopResult(results)?.trim().orEmpty()
            emitEvent(mapOf("type" to "result", "text" to transcript))
            destroyRecognizer()
        }

        override fun onPartialResults(partialResults: Bundle?) {
            val transcript = extractTopResult(partialResults)?.trim().orEmpty()
            if (transcript.isEmpty()) {
                return
            }
            latestPartial = transcript
            consecutiveRecoverableErrors = 0
            emitEvent(mapOf("type" to "partial", "text" to transcript))
        }

        override fun onEvent(eventType: Int, params: Bundle?) = Unit

        private fun extractTopResult(results: Bundle?): String? {
            val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            return matches?.firstOrNull()
        }

        private fun startRecognizer(resetPartial: Boolean) {
            cancelPendingRestart()
            if (resetPartial) {
                latestPartial = ""
            }

            val recognizer = SpeechRecognizer.createSpeechRecognizer(activity)
            recognizer.setRecognitionListener(this)
            speechRecognizer = recognizer

            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(
                    RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                )
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, activeLocale)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false)
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, activity.packageName)
                putExtra(
                    RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS,
                    4000L,
                )
                putExtra(
                    RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS,
                    1200L,
                )
                putExtra(
                    RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS,
                    1800L,
                )
            }

            emitEvent(mapOf("type" to "state", "value" to "start_requested"))
            recognizer.startListening(intent)
        }

        private fun scheduleRestart() {
            cancelPendingRestart()
            destroyRecognizer()
            emitEvent(
                mapOf(
                    "type" to "state",
                    "value" to "restart_scheduled",
                    "attempt" to consecutiveRecoverableErrors,
                ),
            )
            pendingRestart = Runnable {
                if (stopRequested) {
                    return@Runnable
                }
                emitEvent(
                    mapOf(
                        "type" to "state",
                        "value" to "restart_requested",
                        "attempt" to consecutiveRecoverableErrors,
                    ),
                )
                startRecognizer(resetPartial = false)
            }.also { handler.postDelayed(it, RESTART_DELAY_MS) }
        }

        private fun cancelPendingRestart() {
            pendingRestart?.let(handler::removeCallbacks)
            pendingRestart = null
        }

        private fun emitEvent(event: Map<String, Any>) {
            onEvent(
                event + mapOf(
                    "requestId" to requestId,
                    "emittedAtMs" to System.currentTimeMillis(),
                ),
            )
        }

        private fun destroyRecognizer() {
            cancelPendingRestart()
            runCatching { speechRecognizer?.destroy() }
            speechRecognizer = null
        }

        private fun speechErrorCode(error: Int): String {
            return when (error) {
                SpeechRecognizer.ERROR_AUDIO -> "error_audio"
                SpeechRecognizer.ERROR_CLIENT -> "error_client"
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "error_permissions"
                SpeechRecognizer.ERROR_NETWORK -> "error_network"
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "error_network_timeout"
                SpeechRecognizer.ERROR_NO_MATCH -> "error_no_match"
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "error_busy"
                SpeechRecognizer.ERROR_SERVER -> "error_server"
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "error_speech_timeout"
                else -> "error_unknown_$error"
            }
        }

        companion object {
            private const val MAX_RECOVERABLE_ERRORS = 4
            private const val RESTART_DELAY_MS = 120L
        }
    }

    private class NativePcmRecorder(
        private val path: String,
        private val onRms: (Double) -> Unit,
        private val onError: (String, String) -> Unit,
    ) {
        @Volatile
        private var running = false

        private var audioRecord: AudioRecord? = null
        private var outputStream: FileOutputStream? = null
        private var captureThread: Thread? = null
        private var totalAudioBytes: Long = 0

        fun start() {
            val minBufferSize = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
            )
            if (minBufferSize <= 0) {
                throw IllegalStateException("Invalid AudioRecord buffer size: $minBufferSize")
            }

            val file = File(path)
            file.parentFile?.mkdirs()
            outputStream = FileOutputStream(file).also { stream ->
                stream.write(ByteArray(WAV_HEADER_SIZE))
            }

            val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                AudioRecord.Builder()
                    .setAudioSource(MediaRecorder.AudioSource.MIC)
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AUDIO_FORMAT)
                            .setSampleRate(SAMPLE_RATE)
                            .setChannelMask(CHANNEL_CONFIG)
                            .build(),
                    )
                    .setBufferSizeInBytes(max(minBufferSize, FRAME_BYTES * 4))
                    .build()
            } else {
                @Suppress("DEPRECATION")
                AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    CHANNEL_CONFIG,
                    AUDIO_FORMAT,
                    max(minBufferSize, FRAME_BYTES * 4),
                )
            }

            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                recorder.release()
                throw IllegalStateException("AudioRecord failed to initialize.")
            }

            audioRecord = recorder
            running = true
            recorder.startRecording()

            captureThread = Thread {
                val buffer = ByteArray(FRAME_BYTES)
                try {
                    while (running) {
                        val read = recorder.read(buffer, 0, buffer.size)
                        if (read <= 0) {
                            continue
                        }
                        outputStream?.write(buffer, 0, read)
                        totalAudioBytes += read.toLong()
                        onRms(calculateRmsDb(buffer, read))
                    }
                } catch (error: Exception) {
                    onError("capture_failed", error.message ?: "PCM capture failed.")
                }
            }.also { it.start() }
        }

        fun stop(): String? {
            val activePath = path
            shutdown(deleteFile = false)
            return activePath
        }

        fun cancel() {
            shutdown(deleteFile = true)
        }

        private fun shutdown(deleteFile: Boolean) {
            running = false
            audioRecord?.let { recorder ->
                try {
                    recorder.stop()
                } catch (_: Exception) {
                }
            }
            try {
                captureThread?.join(800)
            } catch (_: InterruptedException) {
            }
            captureThread = null

            audioRecord?.let { recorder ->
                recorder.release()
            }
            audioRecord = null

            outputStream?.flush()
            outputStream?.close()
            outputStream = null

            if (!deleteFile) {
                writeWavHeader(path, totalAudioBytes)
            } else {
                runCatching { File(path).delete() }
            }
        }

        private fun calculateRmsDb(buffer: ByteArray, length: Int): Double {
            if (length < 2) {
                return MIN_DB
            }

            val samples = length / 2
            var sumSquares = 0.0
            val wrapped = ByteBuffer.wrap(buffer, 0, length).order(ByteOrder.LITTLE_ENDIAN)
            repeat(samples) {
                val sample = wrapped.short.toInt()
                sumSquares += sample * sample.toDouble()
            }
            if (samples == 0) {
                return MIN_DB
            }

            val rms = sqrt(sumSquares / samples) / Short.MAX_VALUE.toDouble()
            if (rms <= 0.0) {
                return MIN_DB
            }
            return (20.0 * (ln(rms) / ln(10.0))).coerceIn(MIN_DB, 0.0)
        }

        private fun writeWavHeader(path: String, audioBytes: Long) {
            RandomAccessFile(path, "rw").use { file ->
                val totalDataLen = audioBytes + 36
                val byteRate = SAMPLE_RATE * CHANNEL_COUNT * BITS_PER_SAMPLE / 8
                val header = ByteBuffer.allocate(WAV_HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN).apply {
                    put("RIFF".toByteArray())
                    putInt(totalDataLen.toInt())
                    put("WAVE".toByteArray())
                    put("fmt ".toByteArray())
                    putInt(16)
                    putShort(1)
                    putShort(CHANNEL_COUNT.toShort())
                    putInt(SAMPLE_RATE)
                    putInt(byteRate)
                    putShort((CHANNEL_COUNT * BITS_PER_SAMPLE / 8).toShort())
                    putShort(BITS_PER_SAMPLE.toShort())
                    put("data".toByteArray())
                    putInt(audioBytes.toInt())
                }.array()
                file.seek(0)
                file.write(header)
            }
        }
    }

    companion object {
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_COUNT = 1
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        private const val BITS_PER_SAMPLE = 16
        private const val FRAME_MILLIS = 30
        private const val FRAME_BYTES =
            SAMPLE_RATE * CHANNEL_COUNT * (BITS_PER_SAMPLE / 8) * FRAME_MILLIS / 1000
        private const val WAV_HEADER_SIZE = 44
        private const val MIN_DB = -160.0
        private const val TTS_TO_STT_ECHO_SETTLE_MS = 400L
    }
}
