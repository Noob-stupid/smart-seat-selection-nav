/* 真实后端 API 客户端：通过 fetch 访问 Flask 接口
   ------------------------------------------------------------------
   混合模式：优先使用真实后端；当请求发生「网络层失败」（连不上 Flask，
   例如 file:// 打开或纯静态服务器）时，若页面同时引入了 mock-api.js
   （它会挂载 window.__mockAxios），则自动回退到浏览器内 mock，
   保证离线演示仍可用。
   注意：仅网络失败才回退；后端返回的 4xx/5xx 属真实业务错误，不被掩盖。
*/
(function () {
  'use strict';

  // 声明「真实 API 可用」，供随后加载的 mock-api.js 判断是否需要接管 axios
  window.__REAL_API_AVAILABLE = true;

  function normalizePath(path) {
    return path || '/';
  }
  window.normalizePath = normalizePath;

  var baseURL = (typeof window !== 'undefined' && window.API_BASE_URL) || '';

  function buildUrl(url, params) {
    var u = baseURL + url;
    if (!params) return u;
    var qs = Object.keys(params).filter(function (k) {
      return params[k] !== undefined && params[k] !== null && params[k] !== '';
    }).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
    }).join('&');
    return qs ? u + (u.indexOf('?') >= 0 ? '&' : '?') + qs : u;
  }

  function request(method, url, data, config) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (config && config.headers) {
      Object.keys(config.headers).forEach(function (k) { opts.headers[k] = config.headers[k]; });
    }
    if (data !== undefined && data !== null) {
      if (typeof FormData !== 'undefined' && data instanceof FormData) {
        opts.body = data;
        delete opts.headers['Content-Type'];
      } else {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(data);
      }
    }
    var params = (method === 'GET' || method === 'DELETE') && config ? config.params : null;
    return fetch(buildUrl(url, params), opts).then(function (res) {
      return res.text().then(function (text) {
        var body = null;
        if (text) {
          try { body = JSON.parse(text); } catch (e) { body = { message: text }; }
        } else {
          body = {};
        }
        if (!res.ok) {
          var err = new Error((body && body.message) || ('HTTP ' + res.status));
          err.response = { status: res.status, data: body };
          throw err;
        }
        return { status: res.status, data: body };
      });
    }, function (netErr) {
      // 仅处理网络层失败（fetch reject）；后端返回的错误状态在上面已抛出不回退
      var mock = window.__mockAxios;
      if (!mock) throw netErr;
      if (window.console && console.info) {
        console.info('[api-client] 后端不可达，已回退到演示数据：', method, url);
      }
      window.__USING_MOCK_API = true;
      var fn = mock[method === 'DELETE' ? 'delete' : String(method).toLowerCase()];
      if (typeof fn !== 'function') throw netErr;
      return method === 'GET' || method === 'DELETE'
        ? fn(url, config)
        : fn(url, data, config);
    });
  }

  window.axios = {
    get: function (url, config) { return request('GET', url, null, config); },
    post: function (url, data, config) { return request('POST', url, data, config); },
    put: function (url, data, config) { return request('PUT', url, data, config); },
    delete: function (url, config) { return request('DELETE', url, null, config); }
  };
})();
