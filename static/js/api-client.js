/* 真实后端 API 客户端：替代原 mock-api.js，通过 fetch 访问 Flask 接口 */
(function () {
  'use strict';

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
    });
  }

  window.axios = {
    get: function (url, config) { return request('GET', url, null, config); },
    post: function (url, data, config) { return request('POST', url, data, config); },
    put: function (url, data, config) { return request('PUT', url, data, config); },
    delete: function (url, config) { return request('DELETE', url, null, config); }
  };
})();
