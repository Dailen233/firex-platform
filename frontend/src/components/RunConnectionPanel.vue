<script setup lang="ts">
import { ref } from 'vue'
import { PlugZap, Unplug, ShieldQuestion, RefreshCw, FlaskConical, CircleCheck, TriangleAlert } from 'lucide-vue-next'
import { useRunConnection } from '../lib/run-connection'

const {
  status, runId, health, snapshot, error,
  lastSuccessfulQueryAt, lastNewRevisionAt, observationTimeLabel,
  connect, disconnect,
} = useRunConnection()
const input = ref('')

function fmtTime(ms: number | null): string {
  if (ms === null) return '—'
  return new Date(ms).toLocaleTimeString()
}

function submit(): void {
  void connect(input.value)
}
</script>

<template>
  <section class="run-connection">
    <div class="panel-eyebrow">火情监测<PlugZap :size="16" /></div>
    <p class="small muted">输入由平台提供的监测任务编号，查看该任务收到的火情信息。</p>

    <div v-if="status !== 'disconnected'" class="run-status-line">
      <span v-if="status === 'connecting'" class="tag neutral"><RefreshCw :size="13" class="spin" />正在连接…</span>
      <span v-else-if="status === 'connected'" class="tag ok"><CircleCheck :size="13" />已连接</span>
      <span v-else class="tag danger"><TriangleAlert :size="13" />连接异常</span>
      <span class="run-id">当前任务：{{ runId }}</span>
    </div>

    <div class="conn-form">
      <input v-model="input" type="text" placeholder="监测任务编号（由平台提供）" spellcheck="false" :disabled="status === 'connecting'" @keyup.enter="submit" />
      <button v-if="status === 'disconnected' || status === 'error'" class="primary-button small" @click="submit" :disabled="!input.trim()">连接数据</button>
      <button v-else class="secondary-button small" @click="disconnect"><Unplug :size="14" />断开</button>
    </div>

    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <template v-if="health">
      <dl class="conn-facts">
        <div><dt>火点识别</dt><dd>{{ health.algorithm_mode === 'unconfigured' ? '暂未启用' : '已启用' }}</dd></div>
        <div><dt>运行模式</dt><dd>{{ health.processing_mode === 'fixture' ? '平台演示数据' : health.processing_mode === 'unconfigured' ? '暂未启用' : '运行中' }}</dd></div>
      </dl>
    </template>

    <template v-if="snapshot">
      <div v-if="snapshot.state_status !== 'observation'" class="notice amber"><ShieldQuestion :size="14" />尚未收到观测数据，当前情况未知，不能视为无火。</div>
      <div v-else class="snapshot-facts">
        <div class="snapshot-head"><FlaskConical :size="15" /><strong>{{snapshot.result_origin==='yolo'?(snapshot.input_source==='simulation'?'模拟观测数据':'现场影像数据'):'平台测试数据'}}</strong></div>
        <dl class="conn-facts">
          <div><dt>观测时间</dt><dd>{{ observationTimeLabel }}</dd></div>
          <div><dt>识别到的火点</dt><dd v-if="snapshot.result_origin==='yolo'">{{ snapshot.detections?.length??0 }} 个</dd><dd v-else>{{ snapshot.patches.length }} 个区域</dd></div>
        </dl>
      </div>
    </template>

    <div class="timing-facts">
      <span>最近同步：{{ fmtTime(lastSuccessfulQueryAt) }}</span>
      <span>最近收到新结果：{{ fmtTime(lastNewRevisionAt) }}</span>
    </div>
  </section>
</template>

<style scoped>
.run-connection{border:1px solid var(--border);border-radius:8px;padding:13px;background:#0d1a26}
.run-status-line{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.run-id{font-family:var(--mono,monospace);font-size:.75rem;color:#a9c0cf;word-break:break-all}
.conn-form{display:flex;gap:7px}
.conn-form input{flex:1;min-width:0}
.small{padding:6px 10px;font-size:.8125rem}
.run-binding{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.conn-facts{margin:8px 0 0}
.conn-facts>div{display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--border);padding:5px 0;font-size:.8125rem}
.conn-facts>div:first-child{border-top:0}
.conn-facts dt{color:#a9c0cf}
.conn-facts dd{font-variant-numeric:tabular-nums}
.snapshot-facts{margin-top:8px}
.snapshot-head{display:flex;align-items:center;gap:6px;color:#ffb066;margin-bottom:4px}
.timing-facts{display:flex;flex-direction:column;gap:3px;margin-top:9px;font-size:.75rem;color:#7d94a5;font-variant-numeric:tabular-nums}
.spin{animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
