/* 个人中心 Vue 应用 */
(function () {
  if (typeof Vue === 'undefined') {
    document.querySelectorAll('[v-cloak]').forEach(function (el) { el.removeAttribute('v-cloak') });
    return;
  }
  try {
    Vue.createApp({
      delimiters: ['${', '}'],
      data() {
        return {
          loading: true,
          saving: false,
          pwSaving: false,
          user: {},
          edit: { name: '', email: '', phone: '', tags: [] },
          pw: { old: '', new1: '', new2: '' },
          newTag: '',
          allTags: ['安静学习', '靠窗座位', '需要电源', '阳光充足', '角落位置', '小组讨论', '无需电源', '离门近', '离卫生间近', '顶层', '低层'],
        };
      },
      created() { this.loadProfile(); },
      methods: {
        async loadProfile() {
          this.loading = true;
          try {
            var res = await api.get('/api/auth/me');
            this.user = res.data || {};
            var prefs = this.user.preferences || {};
            this.edit.name = this.user.name || '';
            this.edit.email = this.user.email || '';
            this.edit.phone = this.user.phone || '';
            this.edit.tags = Array.isArray(prefs.tags) ? prefs.tags : [];
          } catch (e) { showToast('加载失败', 'error'); }
          finally { this.loading = false; }
        },

        toggleTag(tag) {
          var idx = this.edit.tags.indexOf(tag);
          if (idx >= 0) this.edit.tags.splice(idx, 1);
          else this.edit.tags.push(tag);
        },

        addCustomTag() {
          var t = this.newTag.trim();
          if (!t) return;
          if (this.edit.tags.includes(t)) return;
          this.edit.tags.push(t);
          this.newTag = '';
        },

        async saveProfile() {
          this.saving = true;
          try {
            var res = await api.put('/api/profile', {
              name: this.edit.name,
              email: this.edit.email,
              phone: this.edit.phone,
              tags: this.edit.tags,
            });
            this.user = res.data || {};
            showToast('资料已保存');
          } catch (e) { }
          finally { this.saving = false; }
        },

        triggerUpload() { this.$refs.avatarInput.click(); },

        async uploadAvatar(e) {
          var file = e.target.files[0];
          if (!file) return;
          var formData = new FormData();
          formData.append('avatar', file);
          try {
            var res = await axios.post('/api/profile/avatar', formData, {
              headers: { 'Content-Type': 'multipart/form-data' },
            });
            this.user.avatar_url = res.data.data.avatar_url;
            showToast('头像已更新');
          } catch (e) { showToast('上传失败', 'error'); }
        },

        async changePassword() {
          if (!this.pw.old || !this.pw.new1) { showToast('请填写密码', 'error'); return; }
          if (this.pw.new1.length < 6) { showToast('新密码至少6位', 'error'); return; }
          if (this.pw.new1 !== this.pw.new2) { showToast('两次输入不一致', 'error'); return; }
          this.pwSaving = true;
          try {
            await api.put('/api/profile/password', {
              old_password: this.pw.old,
              new_password: this.pw.new1,
            });
            showToast('密码已修改');
            this.pw = { old: '', new1: '', new2: '' };
          } catch (e) { }
          finally { this.pwSaving = false; }
        },
      },
    }).mount('#app');
  } catch (e) {
    console.error('[个人中心] Vue 初始化失败:', e);
    document.querySelectorAll('[v-cloak]').forEach(function (el) { el.removeAttribute('v-cloak') });
  }
})();
