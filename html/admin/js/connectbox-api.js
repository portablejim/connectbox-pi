/* eslint-env browser */
/* global ConnectBoxApp */
/* eslint no-use-before-define: "off" */
var ConnectBoxApp = (function (App, $) {
  'use strict'

  var apiEnum = {
    ENDPOINT: 'api'
  }

  function buildApiUrl (resource, params) {
    var baseurl = apiEnum.ENDPOINT + '/' + resource

    if (params) {
      return baseurl + Object.keys(params).reduce(function (previousValue, currentValue) {
        return previousValue + '&' + currentValue + '=' + encodeURIComponent(params[currentValue])
      }, '')
    } else {
      return baseurl
    }
  }

  App.api = {
    getProperty: function (propertyName, callback) {
      $.ajax({
        url: buildApiUrl(propertyName, {}),
        method: 'GET',
        success: function (data, textStatus, jqXHR) {
          window.mydata = data
          if (data.code === 0) {
            if (callback) {
              callback(data.result)
            }
          } else {
            if (callback) {
              callback(null, data.code, data.result)
            }
          }
        },
        error: function (jqXHR, textStatus, errorThrown) {
          if (callback) {
            callback(null, 500, 'Unexpected error getting property: ' + textStatus)
          }
        }
      })
    },

    setProperty: function (propertyName, propertyValue, wrap, callback) {
      $.ajax({
        url: buildApiUrl(propertyName, {}),
        method: 'PUT',
        dataType: 'json',
        data: wrap ? '{"value": "' + propertyValue + '"}' : propertyValue,
        success: function (data, textStatus, jqXHR) {
          window.mydata = data
          if (data.code === 0) {
            if (callback) {
              callback(data.result)
            }
          } else {
            if (callback) {
              callback(null, data.code, data.result)
            }
          }
        },
        error: function (jqXHR, textStatus, errorThrown) {
          if (callback) {
            callback(null, 500, 'Unexpected error setting property: ' + textStatus)
          }
        }
      })
    },

    triggerEvent: function (propertyName, eventType, callback) {
      $.ajax({
        url: buildApiUrl(propertyName, {}),
        method: 'POST',
        dataType: 'json',
        data: '{"value": "' + eventType + '"}',
        success: function (data, textStatus, jqXHR) {
          window.mydata = data
          if (data.code === 0) {
            if (callback) {
              callback(data.result)
            }
          } else {
            if (callback) {
              callback(null, data.code, data.result)
            }
          }
        },
        error: function (jqXHR, textStatus, errorThrown) {
          if (callback) {
            callback(null, 500, 'Unexpected error triggering event: ' + textStatus)
          }
        }
      })
    }
  }

  return App
}(ConnectBoxApp || {}, jQuery))
