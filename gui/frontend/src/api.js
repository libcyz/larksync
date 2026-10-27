// 前端调用 Python 的唯一入口：打包后走 pywebview 桥，浏览器开发时走 mock
import { ref } from 'vue'
import { mock } from './mock.js'

// 写入 / 撤销的进度 { stage, done, total }：Python 通过 window.larksyncProgress 推过来
export const progress = ref(null)
window.larksyncProgress = (p) => { progress.value = p }

// 打包后的桌面应用里为 true：选文件、拖入文件走 Python（能拿到真实路径）
export const native = !import.meta.env.DEV

const ready = import.meta.env.DEV
  ? Promise.resolve(mock)
  : new Promise((resolve) => {
      if (window.pywebview) resolve(window.pywebview.api)
      else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api))
    })

export async function call(name, arg) {
  const api = await ready
  const res = await api[name](arg)
  if (res && res.error) throw new Error(res.error)
  return res
}

// 文件 → base64，交给 Python 解码（兼容 Excel 存的 GBK CSV）
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result.split(',')[1])
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}
