<script setup lang="ts">
import { ref } from 'vue'
import { PlugZap, Unplug, ShieldQuestion, RefreshCw, FlaskConical, CircleCheck, TriangleAlert } from 'lucide-vue-next'
import { useRunConnection } from '../lib/run-connection'

const {
  status, runId, health, run, snapshot, error,
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
    <div class="panel-eyebrow"><span>运行状态</span><PlugZap :size="16" /></div>

    <div v-if="status !== 'disconnected'" class="run-status-line">
      <span v-if="status === 'connecting'" class="tag neutral"><RefreshCw :size="13" class="spin" />正在读取运行</span>
      <span v-else-if="status === 'connected'" class="tag ok"><CircleCheck :size="13" />跟随最新状态</span>
      <span v-else class="tag danger"><TriangleAlert :size="13" />运行连接异常</span>
      <span class="run-id">{{ runId }}</span>
    </div>

    <div class="conn-form">
      <label class="sr-only" for="run-id-input">运行编号</label>
      <input id="run-id-input" v-model="input" type="text" placeholder="粘贴运行编号" spellcheck="false" :disabled="status === 'connecting'" @keyup.enter="submit" />
      <button v-if="status === 'disconnected' || status === 'error'" class="primary-button small" @click="submit" :disabled="!input.trim()">连接</button>
      <button v-else class="secondary-button small" @click="disconnect"><Unplug :size="14" />断开</button>
    </div>

    <div v-if="error" class="notice error" role="alert">
      <TriangleAlert :size="14" />
      <span>{{ snapshot ? '读取失败，暂时保留最近有效状态。' : '连接失败，请核对运行编号或服务状态。' }}</span>
      <details class="error-details"><summary>查看错误信息</summary><span>{{ error }}</span></details>
    </div>

    <template v-if="snapshot">
      <div v-if="snapshot.state_status !== 'observation'" class="notice amber"><ShieldQuestion :size="14" />尚无观测数据；这不表示已确认无火。</div>
      <div v-else class="snapshot-facts">
        <div class="snapshot-head"><FlaskConical :size="15" /><strong>{{snapshot.result_origin==='yolo'?'仿真数据':'接口测试数据'}} · 不代表图像重建</strong></div>
        <dl class="conn-facts">
          <div><dt>观测时间</dt><dd>{{ observationTimeLabel }}</dd></div>
          <div><dt>火区数量</dt><dd>{{ snapshot.patches.length }}</dd></div>
        </dl>
      </div>
    </template>

    <div class="timing-facts">
      <span>最近更新：{{ fmtTime(lastNewRevisionAt) }}</span>
      <span v-if="lastSuccessfulQueryAt !== lastNewRevisionAt">最近成功读取：{{ fmtTime(lastSuccessfulQueryAt) }}</span>
    </div>

    <details v-if="health || run || snapshot" class="technical-details">
      <summary>查看运行与接口详情</summary>
      <template v-if="health">
        <dl class="conn-facts">
          <div><dt>图像算法</dt><dd>{{ health.algorithm_mode === 'unconfigured' ? '尚未接入' : health.algorithm_mode }}</dd></div>
          <div><dt>处理模式</dt><dd>{{ health.processing_mode === 'fixture' ? '接口测试（fixture）' : health.processing_mode }}</dd></div>
        </dl>
      </template>
      <template v-if="run">
        <dl class="conn-facts">
          <div><dt>电厂</dt><dd>{{ run.plant_id }}</dd></div>
          <div><dt>场景</dt><dd>{{ run.scene_id }}</dd></div>
          <div><dt>模型版本</dt><dd>{{ run.asset_version }}</dd></div>
        </dl>
      </template>
      <template v-if="snapshot">
        <dl class="conn-facts">
          <div><dt>数据来源</dt><dd>{{ snapshot.result_origin }}</dd></div>
          <div><dt>版本号</dt><dd>{{ snapshot.revision }}</dd></div>
          <div><dt>提供者版本</dt><dd>{{ snapshot.provider_version }}</dd></div>
        </dl>
      </template>
    </details>
  </section>
</template>

<style scoped>
.run-connection{border:1px solid var(--border);border-radius:8px;padding:13px;background:#0d1a26}
.panel-eyebrow{display:flex;align-items:center;justify-content:space-between;gap:8px}
.run-status-line{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.run-id{font-family:var(--mono,monospace);font-size:.75rem;color:#a9c0cf;word-break:break-all}
.conn-form{display:flex;gap:7px;min-width:0}
.conn-form input{flex:1;min-width:0}
.small{padding:6px 10px;font-size:.8125rem}
.conn-facts{margin:8px 0 0}
.conn-facts>div{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);gap:8px;border-top:1px solid var(--border);padding:5px 0;font-size:.8125rem}
.conn-facts>div:first-child{border-top:0}
.conn-facts dt{color:#a9c0cf}
.conn-facts dd{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;text-align:right}
.snapshot-facts{margin-top:8px}
.snapshot-head{display:flex;align-items:center;gap:6px;color:#ffb066;margin-bottom:4px}
.timing-facts{display:flex;flex-direction:column;gap:3px;margin-top:9px;font-size:.75rem;color:#a9c0cf;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.technical-details{margin-top:10px;border-top:1px solid var(--border);padding-top:8px;font-size:.8125rem}
.technical-details summary{cursor:pointer;color:#a9c0cf;min-height:28px;display:flex;align-items:center}
.error-details{flex-basis:100%;min-width:0}
.error-details summary{cursor:pointer;margin:3px 0}
.error-details span{overflow-wrap:anywhere}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:420px){.run-connection{padding:10px}.run-status-line{align-items:flex-start;flex-direction:column;gap:5px}.conn-facts>div{grid-template-columns:minmax(0,1fr) minmax(0,1.1fr)}}
.spin{animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
