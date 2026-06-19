package com.giraffetechnology.qcpad.ui.qc

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.View
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.giraffetechnology.qcpad.R
import com.giraffetechnology.qcpad.config.SessionConfig
import com.giraffetechnology.qcpad.databinding.ActivityQcBinding
import com.giraffetechnology.qcpad.model.AggregateStatus
import com.giraffetechnology.qcpad.ui.login.LoginActivity
import com.giraffetechnology.qcpad.ui.qc.camera.UvcCameraSource
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

class QcActivity : AppCompatActivity() {

    private lateinit var binding: ActivityQcBinding
    private val viewModel: QcViewModel by viewModels()
    private lateinit var cameraSource: UvcCameraSource

    private val inactivityHandler = Handler(Looper.getMainLooper())
    private val logoutRunnable = Runnable { logout() }
    private val timeoutMs = TimeUnit.MINUTES.toMillis(SessionConfig.INACTIVITY_TIMEOUT_MINUTES)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityQcBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupCamera()
        binding.btnLogout.setOnClickListener { logout() }
        observeUiState()
        resetInactivityTimer()
    }

    private fun setupCamera() {
        cameraSource = UvcCameraSource(this)

        binding.surfaceViewCamera.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                if (cameraSource.isConnected) {
                    cameraSource.attach(holder.surface)
                }
            }
            override fun surfaceChanged(holder: SurfaceHolder, fmt: Int, w: Int, h: Int) {}
            override fun surfaceDestroyed(holder: SurfaceHolder) {
                cameraSource.detach()
            }
        })

        cameraSource.startMonitoring(
            onConnected = {
                runOnUiThread {
                    binding.cameraPlaceholder.visibility = View.GONE
                    val surface = binding.surfaceViewCamera.holder.surface
                    if (surface.isValid) cameraSource.attach(surface)
                }
            },
            onDisconnected = {
                runOnUiThread {
                    binding.cameraPlaceholder.visibility = View.VISIBLE
                }
            }
        )
    }

    private fun observeUiState() {
        lifecycleScope.launch {
            viewModel.uiState.collect { renderState(it) }
        }
    }

    private fun renderState(state: QcUiState) {
        val result = state.lastResult
        if (result != null) {
            binding.tvDetectionResult.visibility = View.VISIBLE
            if (result.passed) {
                binding.tvDetectionResult.text = getString(R.string.result_pass)
                binding.tvDetectionResult.setTextColor(
                    ContextCompat.getColor(this, R.color.pass_green)
                )
            } else {
                binding.tvDetectionResult.text = getString(R.string.result_fail)
                binding.tvDetectionResult.setTextColor(
                    ContextCompat.getColor(this, R.color.fail_red)
                )
            }
        } else {
            binding.tvDetectionResult.visibility = View.INVISIBLE
        }

        when (state.aggregateStatus) {
            AggregateStatus.PASS -> {
                binding.aggregateStatusBlock.setBackgroundColor(
                    ContextCompat.getColor(this, R.color.pass_green)
                )
                binding.tvAggregateLabel.text = getString(R.string.aggregate_pass)
            }
            AggregateStatus.FAIL -> {
                binding.aggregateStatusBlock.setBackgroundColor(
                    ContextCompat.getColor(this, R.color.fail_red)
                )
                binding.tvAggregateLabel.text = getString(R.string.aggregate_fail)
            }
            AggregateStatus.UNKNOWN -> {
                binding.aggregateStatusBlock.setBackgroundColor(
                    ContextCompat.getColor(this, R.color.neutral_gray)
                )
                binding.tvAggregateLabel.text = getString(R.string.aggregate_waiting)
            }
        }
    }

    override fun dispatchTouchEvent(ev: MotionEvent?): Boolean {
        resetInactivityTimer()
        return super.dispatchTouchEvent(ev)
    }

    private fun resetInactivityTimer() {
        inactivityHandler.removeCallbacks(logoutRunnable)
        inactivityHandler.postDelayed(logoutRunnable, timeoutMs)
    }

    private fun logout() {
        inactivityHandler.removeCallbacks(logoutRunnable)
        startActivity(
            Intent(this, LoginActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            }
        )
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraSource.destroy()
        inactivityHandler.removeCallbacks(logoutRunnable)
    }
}
