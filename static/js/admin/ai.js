/* ============================================================
   管理端 AI 运营中心
   ------------------------------------------------------------
   * 大模型配置支持在页面上直接切换供应商（保存后立即生效，无需重启）
   * 密钥只提交、不回显；留空表示不修改
   ============================================================ */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],

  data() {
    return {
      status: {},
      cfg: {
        ai_enabled: true,
        ai_provider: 'deepseek',
        ai_model: '',
        ai_base_url: '',
        ai_api_key_set: false,
        ai_api_key_masked: '',
        ai_timeout: 20,
        ai_max_tokens: 600,
        ai_temperature: 0.3,
        ai_cache_ttl: 60,
        ai_provider_presets: {},
        // ---- 智能终端显示位置 ----
        terminal_building_id: 0,
        terminal_floor_id: 0,
        terminal_title: '智能座位导引',
        buildings: [],
        floors: [],
      },
      apiKeyInput: '',
      testResult: null,
      report: null,
      anomaly: null,
      trend: null,
      trendDays: 7,
      answer: null,
      question: '',
      showTerminalApi: false,
      busy: { save: false, test: false, reload: false, cache: false, report: false, anomaly: false, trend: false, ask: false, terminal: false },
      quickQuestions: [
        '现在哪个楼层最紧张？',
        '当前有没有异常设备？',
        '给一条提升上座率的建议',
      ],
    };
  },

  computed: {
    /** 当前所选场所下的楼层（选"全部场所"时列出全部） */
    floorsOfBuilding() {
      var bid = Number(this.cfg.terminal_building_id) || 0;
      var all = this.cfg.floors || [];
      if (!bid) return all;
      return all.filter(function (f) { return Number(f.building_id) === bid; });
    },
  },

  mounted() {
    this.loadStatus();
    this.loadCfg();
  },

  methods: {
    // ---------------- 状态 ----------------
    async loadStatus() {
      try {
        const res = await api.get('/api/ai/status');
        this.status = res.data || {};
      } catch (e) { /* toast 已提示 */ }
    },

    async loadCfg() {
      try {
        const res = await api.get('/api/admin/config');
        const d = res.data || {};
        Object.keys(this.cfg).forEach((k) => {
          if (d[k] !== undefined) this.cfg[k] = d[k];
        });
      } catch (e) { /* ignore */ }
    },

    onProviderChange() {
      // 切换供应商时，自动套用该供应商的默认地址与模型
      const preset = this.cfg.ai_provider_presets[this.cfg.ai_provider];
      if (preset) {
        this.cfg.ai_base_url = preset.base_url;
        this.cfg.ai_model = preset.model;
      }
      showToast('已套用 ' + this.cfg.ai_provider + ' 预设，记得点保存', 'success');
    },

    async saveCfg() {
      this.busy.save = true;
      try {
        const payload = {
          ai_enabled: this.cfg.ai_enabled,
          ai_provider: this.cfg.ai_provider,
          ai_base_url: this.cfg.ai_base_url,
          ai_model: this.cfg.ai_model,
          ai_timeout: this.cfg.ai_timeout,
          ai_max_tokens: this.cfg.ai_max_tokens,
          ai_temperature: this.cfg.ai_temperature,
          ai_cache_ttl: this.cfg.ai_cache_ttl,
        };
        // 只有用户真的输入了才提交密钥（留空=不修改）
        if (this.apiKeyInput) payload.ai_api_key = this.apiKeyInput;

        const res = await api.put('/api/admin/config', payload);
        showToast(res.message || '配置已保存', 'success');
        this.apiKeyInput = '';
        await this.loadCfg();
        await this.loadStatus();
      } catch (e) { /* toast 已提示 */ }
      this.busy.save = false;
    },

    async testAI() {
      this.busy.test = true;
      this.testResult = null;
      try {
        const res = await api.post('/api/admin/ai/test', {});
        this.testResult = Object.assign({ ok: true }, res.data || {});
        showToast('AI 连接正常', 'success');
      } catch (err) {
        const d = (err.response && err.response.data) || {};
        this.testResult = Object.assign({ ok: false, reason: d.message || '调用失败' }, d.data || {});
      }
      this.busy.test = false;
      this.loadStatus();
    },

    /** 保存智能终端显示位置 */
    async saveTerminal() {
      this.busy.terminal = true;
      try {
        const res = await api.put('/api/admin/config', {
          terminal_building_id: Number(this.cfg.terminal_building_id) || 0,
          terminal_floor_id: Number(this.cfg.terminal_floor_id) || 0,
          terminal_title: this.cfg.terminal_title || '',
        });
        showToast(res.message || '终端位置已保存', 'success');
        await this.loadCfg();
      } catch (e) { /* toast 已提示 */ }
      this.busy.terminal = false;
    },

    async reloadAI() {
      this.busy.reload = true;
      try {
        const res = await api.post('/api/admin/ai/reload', {});
        showToast(res.message || '已重载', 'success');
        await this.loadStatus();
      } catch (e) { /* ignore */ }
      this.busy.reload = false;
    },

    async clearCache() {
      this.busy.cache = true;
      try {
        const res = await api.post('/api/admin/ai/cache/clear', {});
        showToast(res.message || '缓存已清空', 'success');
        await this.loadStatus();
      } catch (e) { /* ignore */ }
      this.busy.cache = false;
    },

    // ---------------- 运营简报 ----------------
    async genReport() {
      this.busy.report = true;
      try {
        const res = await api.get('/api/admin/ai/report');
        this.report = res.data || {};
      } catch (e) { /* ignore */ }
      this.busy.report = false;
    },

    // ---------------- 异常发现 ----------------
    async genAnomaly() {
      this.busy.anomaly = true;
      try {
        const res = await api.get('/api/admin/ai/anomaly');
        this.anomaly = res.data || {};
      } catch (e) { /* ignore */ }
      this.busy.anomaly = false;
    },

    // ---------------- 趋势 ----------------
    async genTrend() {
      this.busy.trend = true;
      try {
        const res = await api.get('/api/admin/ai/trend', { days: this.trendDays });
        this.trend = res.data || {};
      } catch (e) { /* ignore */ }
      this.busy.trend = false;
    },

    // ---------------- 问答 ----------------
    async askAI() {
      if (!this.question) { showToast('请输入问题', 'error'); return; }
      this.busy.ask = true;
      try {
        const res = await api.post('/api/admin/ai/ask', { question: this.question });
        this.answer = res.data || {};
      } catch (e) { /* ignore */ }
      this.busy.ask = false;
    },
  },
}).mount('#app');
