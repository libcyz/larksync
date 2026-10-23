<script setup>
import { computed } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, NGlobalStyle, darkTheme, useOsTheme, zhCN, dateZhCN } from 'naive-ui'
import Main from './components/Main.vue'

const osTheme = useOsTheme()
const theme = computed(() => (osTheme.value === 'dark' ? darkTheme : null))
const overrides = { common: { primaryColor: '#3370ff', primaryColorHover: '#4e83fd', primaryColorPressed: '#245bdb' } }
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="overrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-global-style />
    <n-message-provider>
      <n-dialog-provider>
        <Main />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
