package com.giraffetechnology.qcpad.ui.login

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.giraffetechnology.qcpad.databinding.ActivityLoginBinding
import com.giraffetechnology.qcpad.ui.qc.QcActivity
import com.google.android.material.tabs.TabLayout
import kotlinx.coroutines.launch

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private val viewModel: LoginViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupTabs()
        setupLoginButton()
        observeState()
    }

    private fun setupTabs() {
        binding.tabLayout.addTab(binding.tabLayout.newTab().setText(R.string.tab_account))
        binding.tabLayout.addTab(binding.tabLayout.newTab().setText(R.string.tab_wechat))
        showAccountTab()

        binding.tabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                when (tab.position) {
                    0 -> showAccountTab()
                    1 -> showWechatTab()
                }
            }
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })
    }

    private fun showAccountTab() {
        binding.accountLoginGroup.visibility = View.VISIBLE
        binding.wechatLoginGroup.visibility = View.GONE
    }

    private fun showWechatTab() {
        binding.accountLoginGroup.visibility = View.GONE
        binding.wechatLoginGroup.visibility = View.VISIBLE
    }

    private fun setupLoginButton() {
        binding.btnLogin.setOnClickListener {
            binding.tilPassword.error = null
            viewModel.login(
                binding.etUsername.text.toString(),
                binding.etPassword.text.toString()
            )
        }
    }

    private fun observeState() {
        lifecycleScope.launch {
            viewModel.state.collect { state ->
                when (state) {
                    is LoginState.Idle -> {
                        binding.progressBar.visibility = View.GONE
                        binding.btnLogin.isEnabled = true
                    }
                    is LoginState.Loading -> {
                        binding.progressBar.visibility = View.VISIBLE
                        binding.btnLogin.isEnabled = false
                        binding.tilPassword.error = null
                    }
                    is LoginState.Success -> navigateToQc()
                    is LoginState.Error -> {
                        binding.progressBar.visibility = View.GONE
                        binding.btnLogin.isEnabled = true
                        binding.tilPassword.error = state.message
                        viewModel.clearError()
                    }
                }
            }
        }
    }

    private fun navigateToQc() {
        startActivity(Intent(this, QcActivity::class.java))
        finish()
    }
}
