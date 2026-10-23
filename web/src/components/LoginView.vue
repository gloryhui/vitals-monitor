<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-mark">
        <svg fill="none" stroke="currentColor" stroke-width="1.6">
          <rect x="3" y="4" width="18" height="7" rx="2" />
          <rect x="3" y="13" width="18" height="7" rx="2" />
          <path d="M7 7.5h.01M7 16.5h.01" />
        </svg>
      </div>
      <h1>Vitals 服务器状态</h1>
      <p class="login-hint">请使用管理员账号登录后查看。</p>

      <label class="field" for="loginUser">用户名
        <input id="loginUser" v-model.trim="username" class="input" autocomplete="username" autocapitalize="off" spellcheck="false" required />
      </label>
      <label class="field" for="loginPass">密码
        <input id="loginPass" v-model="password" class="input" type="password" autocomplete="current-password" required />
      </label>

      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <button class="btn btn-primary login-submit" type="submit" :disabled="submitting">
        {{ submitting ? "登录中…" : "登录" }}
      </button>
      <p class="login-note">登录状态保存在本浏览器，{{ dash.state.sessionHours }} 小时内无操作会自动失效。</p>
    </form>
  </div>
</template>

<script setup>
import { inject, ref } from "vue";

const dash = inject("dash");
const username = ref("");
const password = ref("");
const error = ref(dash.state.loginMessage || "");
const submitting = ref(false);

async function submit() {
  submitting.value = true;
  error.value = "";
  try {
    await dash.login(username.value, password.value);
    password.value = "";
  } catch (failure) {
    error.value = failure.message || "登录失败";
  } finally {
    submitting.value = false;
  }
}
</script>
