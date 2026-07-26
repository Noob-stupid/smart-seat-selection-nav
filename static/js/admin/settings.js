/* 系统设置页面 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      config: {},
      weights: [0.35, 0.25, 0.25, 0.15],
      lock_m_range: [10, 60],
      lock_n_range: [2, 15],
      lock_t_range: [10, 120],
    };
  },
  computed: {
    weightSum() { return this.weights.reduce((a, b) => a + b, 0); },
  },
  created() { this.loadConfig(); },
  methods: {
    async loadConfig() {
      try {
        const res = await api.get('/api/admin/config');
        const c = res.data;
        this.config = c;
        if (c.ai_weights) this.weights = [...c.ai_weights];
        if (c.lock_m_range) this.lock_m_range = c.lock_m_range;
        if (c.lock_n_range) this.lock_n_range = c.lock_n_range;
        if (c.lock_t_range) this.lock_t_range = c.lock_t_range;
      } catch (e) { console.error(e); }
    },
    async saveConfig() {
      try {
        await api.put('/api/admin/weights', { weights: this.weights });
        await api.put('/api/admin/config', this.config);
        showToast('配置已保存');
      } catch (e) { }
    },
  },
}).mount('#app');
