<script setup>
import { ref, watch } from 'vue'
import { NModal, NForm, NFormItem, NInput, NButton, NSpace, NText, NAlert, useMessage } from 'naive-ui'
import { call } from '../api.js'

const props = defineProps({ show: Boolean, state: Object })
const emit = defineEmits(['update:show', 'changed'])
const message = useMessage()

// 回调端口不在界面上露出：沿用已保存的值，默认 8888（应用后台的重定向地址按 8888 配）
const form = ref({ app_id: '', app_secret: '', port: 8888 })
const busy = ref(false)

watch(() => props.show, (v) => {
  if (v) form.value = { app_id: props.state.app_id || '', app_secret: '', port: props.state.port || 8888 }
})

async function saveAndLogin() {
  if (!form.value.app_id || (!form.value.app_secret && !props.state.configured)) {
    message.warning('请填写 App ID 和 App Secret')
    return
  }
  busy.value = true
  try {
    emit('changed', await call('save_settings', form.value))
    message.info('已在浏览器打开飞书授权页，请点「授权」')
    const s = await call('login')
    emit('changed', s)
    message.success(`已登录：${s.user}`)
    emit('update:show', false)
  } catch (e) {
    message.error(e.message)
  } finally {
    busy.value = false
  }
}

async function logout() {
  emit('changed', await call('logout'))
}
</script>

<template>
  <n-modal :show="show" @update:show="(v) => emit('update:show', v)" preset="card" title="飞书应用与登录"
    style="width: 460px" :mask-closable="state.configured && !!state.user" :closable="state.configured && !!state.user">
    <n-alert v-if="!state.configured" type="info" :show-icon="false" style="margin-bottom: 16px">
      首次使用：填写你自己的飞书自建应用凭证，然后登录授权。之后打开会自动保持登录。
    </n-alert>
    <n-form label-placement="left" label-width="96">
      <n-form-item label="App ID">
        <n-input v-model:value="form.app_id" placeholder="cli_xxxxxxxx" />
      </n-form-item>
      <n-form-item label="App Secret">
        <n-input v-model:value="form.app_secret" type="password" show-password-on="click"
          :placeholder="state.configured ? '已保存（不改就留空）' : ''" />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="space-between" align="center">
        <n-text depth="3">{{ state.user ? `当前账号：${state.user}` : '未登录' }}</n-text>
        <n-space>
          <n-button v-if="state.user" @click="logout">退出登录</n-button>
          <n-button type="primary" :loading="busy" @click="saveAndLogin">
            {{ state.user ? '保存' : '保存并登录' }}
          </n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>
</template>
