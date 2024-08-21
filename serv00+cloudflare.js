addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})


addEventListener('scheduled', event => {
  event.waitUntil(handleScheduled(event.scheduledTime))
})


async function handleRequest(request, env) {
  const url = new URL(request.url)

  if (url.pathname === '/login' && request.method === 'POST') {
    const formData = await request.formData()
    const password = formData.get('password')

    if (password === PASSWORD) {
      const response = new Response(JSON.stringify({ success: true }), {
        headers: { 'Content-Type': 'application/json' }
      })
      response.headers.set('Set-Cookie', `auth=${PASSWORD}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400`)
      return response
    } else {
      return new Response(JSON.stringify({ success: false }), {
        headers: { 'Content-Type': 'application/json' }
      })
    }
  } else if (url.pathname === '/run' && request.method === 'POST') {
    if (!isAuthenticated(request)) {
      return new Response('Unauthorized', { status: 401 })
    }

    await handleScheduled(new Date().toISOString())
    const results = await CRON_RESULTS.get('lastResults', 'json')
    return new Response(JSON.stringify(results), {
      headers: { 'Content-Type': 'application/json' }
    })
  } else if (url.pathname === '/results' && request.method === 'GET') {
    if (!isAuthenticated(request)) {
      return new Response(JSON.stringify({ authenticated: false }), {
        headers: { 'Content-Type': 'application/json' }
      })
    }
    const results = await CRON_RESULTS.get('lastResults', 'json')
    return new Response(JSON.stringify({ authenticated: true, results: results || [] }), {
      headers: { 'Content-Type': 'application/json' }
    })
  } else if (url.pathname === '/check-auth' && request.method === 'GET') {
    return new Response(JSON.stringify({ authenticated: isAuthenticated(request) }), {
      headers: { 'Content-Type': 'application/json' }
    })
  } else {
    // 显示登录页面或结果页面的 HTML
    return new Response(getHtmlContent(), {
      headers: { 'Content-Type': 'text/html' },
    })
  }
}

function isAuthenticated(request, env) {
  const cookies = request.headers.get('Cookie')
  if (cookies) {
    const authCookie = cookies.split(';').find(c => c.trim().startsWith('auth='))
    if (authCookie) {
      const authValue = authCookie.split('=')[1]
      return authValue === PASSWORD
    }
  }
  return false
}

function getHtmlContent() {
  return `
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Serv00 Monitor</title>
    <style>
    div#dashboard {
      max-height: 100%; /* 可以根据需要调整这个高度 */
      max-width: 100%; /* 可以根据需要调整这个宽度 */
      width: 100%; /* 宽度为100%，以适应不同屏幕 */
      overflow-y: auto; /* 当内容超出容器时添加垂直滚动条 */
      overflow-x: auto; /* 当内容超出容器宽度时添加水平滚动条 */
  } 
  input#password {
    max-height: 100%; /* 可以根据需要调整这个高度 */
    max-width: 100%; /* 可以根据需要调整这个宽度 */
    width: auto; /* 宽度为100%，以适应不同屏幕 */
    overflow-y: auto; /* 当内容超出容器时添加垂直滚动条 */
    overflow-x: auto; /* 当内容超出容器宽度时添加水平滚动条 */
    text-align:center;
    padding-left: 1%;
    padding-right: 1%;
}
    body {
      font-family: Arial, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
      padding: 0 10px; /* 增加左右间距以适应小屏幕 */
      transition: background 0.3s, color 0.3s;
      flex-direction: column; /* 允许垂直方向上的元素排列 */
    }
    .container {
      text-align: center;
      padding: 20px;
      border-radius: 12px;
      box-shadow: 0 8px 16px rgba(0,0,0,0.5);
      max-width: 9000px;
      width: 90%; /* 宽度为100%，以适应不同屏幕 */
      transition: background 0.3s, color 0.3s;
    }
    h1 {
      font-size: 2rem;
      margin-bottom: 20px;
      text-shadow: 0 0 10px rgba(20, 255, 236, 0.7);
      transition: color 0.3s;
    }
    input, button {
      margin: 15px 0;
      padding: 12px;
      width: 100%;
      border-radius: 6px;
      border: 1px solid;
      transition: background-color 0.3s, color 0.3s, border-color 0.3s;
    }
    button {
      cursor: pointer;
      justify-content: center; /* 水平居中 */
      transition: all 0.3s;
      font-size: 1rem;
      font-weight: bold;
      box-shadow: 0 4px 8px rgba(0,0,0,0.3);
    }
    #status {
      margin-top: 20px;
      font-weight: bold;
      transition: color 0.3s;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 20px;
    }
    th, td {
      padding: 12px;
      text-align: left;
      border: 1px solid;
      transition: background-color 0.3s, color 0.3s, border-color 0.3s;
      vertical-align: middle;
    }
    th {
      text-align: center;
      font-weight: bold;
    }
    tbody tr:nth-child(even) {
      transition: background-color 0.3s;
    }
    tbody tr:hover {
      transition: background-color 0.3s;
    }
    .success {
      color: green;
      background-color: rgba(0, 128, 0, 0.2);
      font-weight: bold;
      transition: color 0.3s;
    }
    .failed {
      color: red;
      background-color: rgba(255, 0, 0, 0.2);
      font-weight: bold;
      transition: color 0.3s;
    }
    #themeToggle {
      position: fixed; /* 位置固定，跟随页面滚动 */
      top: 20px;
      right: 20px;
      padding: 8px 12px;
      background-color: #1b1b2f;
      color: white;
      border: none;
      border-radius: 5px;
      cursor: pointer;
      transition: background-color 0.3s, color 0.3s;
      width: auto;
      min-width: 100px;
      text-align: center;
    }

    /* 默认深色模式 */
    body.dark {
      background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460, #1a1a2e);
      color: #fff;
    }
    .container.dark {
      background: #212b40;
      color: #fff;
    }
    h1.dark {
      color: #14ffec;
    }
    input.dark, button.dark {
      background-color: #1b1b2f;
      color: #fff;
      border-color: #0f3460;
    }
    button.dark {
      background: linear-gradient(145deg, #0d7377, #14ffec);
    }
    th.dark {
      background-color: #2c3e50;
      color: #fff;
      border-color: #0f3460;
    }
    td.dark {
      color: #e0e0e0;
      border-color: #0f3460;
    }
    tbody tr:nth-child(even).dark {
      background-color: #1a1a2e;
    }
    tbody tr:hover.dark {
      background-color: #16213e;
    }

    /* 浅色模式 */
    body.light {
      background: linear-gradient(135deg, #f5f7fa, #c3cfe2);
      color: #333;
    }
    .container.light {
      background: #ffffff;
      color: #333;
    }
    h1.light {
      color: #007bff;
    }
    input.light, button.light {
      background-color: #e0e0e0;
      color: #333;
      border-color: #ccc;
    }
    button.light {
      background: linear-gradient(145deg, #007bff, #66aaff);
      color: #fff;
    }
    th.light {
      background-color: #c3cfe2;
      color: #333;
      border-color: #ccc;
    }
    td.light {
      color: #333;
      border-color: #ccc;
    }
    tbody tr:nth-child(even).light {
      background-color: #f5f7fa;
    }
    tbody tr:hover.light {
      background-color: #eaeff7;
    }
    .success.light {
      color: green;
      background-color: rgba(0, 128, 0, 0.2);
    }
    .failed.light {
      color: red;
      background-color: rgba(255, 0, 0, 0.2);
    }

    /* 粉色模式 */
body.pink {
  background: linear-gradient(135deg, #ffe0e9, #ffc3d8);
  color: #333;
}
.container.pink {
  background: #ffe6f0;
  color: #333;
}
h1.pink {
  color: #ff007f;
}
input.pink, button.pink {
  background-color: #ffccd5;
  color: #333;
  border-color: #ff99b5;
}
button.pink {
  background: linear-gradient(145deg, #ff007f, #ff66a3);
  color: #fff;
}
th.pink {
  background-color: #ffc3d8;
  color: #333;
  border-color: #ff99b5;
}
td.pink {
  color: #333;
  border-color: #ff99b5;
}
tbody tr:nth-child(even).pink {
  background-color: #ffe0e9;
}
tbody tr:hover.pink {
  background-color: #ffd6e3;
}
.success.pink {
  color: #008000;
  background-color: rgba(0, 128, 0, 0.2);
}
.failed.pink {
  color: #ff0000;
  background-color: rgba(255, 0, 0, 0.2);
}

/* 彩虹模式 */
body.rainbow {
  background: linear-gradient(135deg, #ff9a9e, #fad0c4, #fbc2eb, #a18cd1, #fbc2eb);
  color: #333;
}
.container.rainbow {
  background: linear-gradient(135deg, rgba(255, 126, 179, 0.8), rgba(255, 101, 163, 0.8), rgba(122, 252, 255, 0.8), rgba(254, 255, 156, 0.8), rgba(162, 255, 153, 0.8));
  color: #333;
  border-radius: 10px;
  padding: 20px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

h1.rainbow {
  color: #ff007f;
  background: linear-gradient(to right, #ff9a9e, #fad0c4, #fbc2eb);
  -webkit-background-clip: text;
  color: transparent;
}
input.rainbow, button.rainbow {
  background-color: #ffdde1;
  color: #333;
  border-color: #ff9a9e;
}
button.rainbow {
  background: linear-gradient(145deg, #fbc2eb, #a18cd1);
  color: #fff;
}
th.rainbow {
  background-color: #fbc2eb;
  color: #333;
  border-color: #ff9a9e;
}
td.rainbow {
  color: #333;
  border-color: #ff9a9e;
}
tbody tr:nth-child(even).rainbow {
  background-color: #fad0c4;
}
tbody tr:hover.rainbow {
  background-color: #fbc2eb;
}
.success.rainbow {
  color: green;
  background-color: rgba(0, 128, 0, 0.2);
}
.failed.rainbow {
  color: red;
  background-color: rgba(255, 0, 0, 0.2);
}



    /* 移动布局 */
    @media (max-width: 768px) {
        body {
            padding: 0 5px; /* 更小的左右间距 */
        }
        .container {
            padding: 15px; /* 减少容器内边距 */
        }
        h1 {
            font-size: 1.5rem; /* 缩小标题字体大小 */
        }
        input, button {
            padding: 10px; /* 缩小输入框和按钮的内边距 */
            font-size: 0.9rem; /* 缩小字体大小 */
        }
        button {
            box-shadow: 0 3px 6px rgba(0,0,0,0.3); /* 减少阴影效果 */
        }
        th, td {
            padding: 8px; /* 缩小表格单元格的内边距 */
            font-size: 0.9rem; /* 缩小表格字体大小 */
        }
        #themeToggle {
            top: 10px;
            right: 10px;
            padding: 6px 10px; /* 缩小主题切换按钮的大小 */
            font-size: 0.8rem; /* 缩小字体大小 */
        }
    }

    @media (max-width: 480px) {
        h1 {
            font-size: 1.2rem; /* 进一步缩小标题字体大小 */
        }
        input, button {
            padding: 8px; /* 进一步缩小输入框和按钮的内边距 */
            font-size: 0.8rem; /* 进一步缩小字体大小 */
        }
        th, td {
            padding: 6px; /* 进一步缩小表格单元格的内边距 */
            font-size: 0.8rem; /* 进一步缩小表格字体大小 */
        }
        #themeToggle {
            top: 5px;
            right: 5px;
            padding: 5px 8px; /* 进一步缩小主题切换按钮的大小 */
            font-size: 0.7rem; /* 进一步缩小字体大小 */
        }
    }
</style>
  </head>
  <body class="dark">
    <button id="themeToggle" class="dark" onclick="toggleTheme()">🌑 Dark Mode</button>
    <div class="container dark">
      <h1 class="dark">Serv00 Monitor</h1>
      <div id="loginForm">
        <input type="password" id="password" placeholder="Enter password" class="dark">
        <button onclick="login()" class="dark">Login</button>
      </div>

      <div id="buttoncontainer">
      <button onclick="runScript()" class="dark">Run Script</button>
      </div>

      <div id="dashboard">
        
        <div id="status" class="dark"></div>
        <table id="resultsTable">
          <thead>
            <tr>
              <th class="dark">Account (账户)</th>
              <th class="dark">Type (类型)</th>
              <th class="dark">Status (状态)</th>
              <th class="dark">Message (信息)</th>
              <th class="dark" style="width: 160px;">Last Run<br>(最后运行时间)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
    <script>
      let password = '';

      function toggleTheme() {
        const body = document.body;
        const container = document.querySelector('.container');
        const h1 = document.querySelector('h1');
        const inputs = document.querySelectorAll('input, button');
        const ths = document.querySelectorAll('th');
        const tds = document.querySelectorAll('td');
        const status = document.getElementById('status');
        const themeToggle = document.getElementById('themeToggle');

        if (body.classList.contains('dark')) {
          body.classList.replace('dark', 'light');
          container.classList.replace('dark', 'light');
          h1.classList.replace('dark', 'light');
          status.classList.replace('dark', 'light');
          themeToggle.classList.replace('dark', 'light');
          themeToggle.textContent = '☀️ Light Mode';
          inputs.forEach(input => input.classList.replace('dark', 'light'));
          ths.forEach(th => th.classList.replace('dark', 'light'));
          tds.forEach(td => td.classList.replace('dark', 'light'));
        } else if (body.classList.contains('light')) {
          body.classList.replace('light', 'pink');
          container.classList.replace('light', 'pink');
          h1.classList.replace('light', 'pink');
          status.classList.replace('light', 'pink');
          themeToggle.classList.replace('light', 'pink');
          themeToggle.textContent = '🌸 Pink Mode';
          inputs.forEach(input => input.classList.replace('light', 'pink'));
          ths.forEach(th => th.classList.replace('light', 'pink'));
          tds.forEach(td => td.classList.replace('light', 'pink'));
        }  else if (body.classList.contains('pink')) {
          body.classList.replace('pink', 'rainbow');
          container.classList.replace('pink', 'rainbow');
          h1.classList.replace('pink', 'rainbow');
          status.classList.replace('pink', 'rainbow');
          themeToggle.classList.replace('pink', 'rainbow');
          themeToggle.textContent = '🌈 Rainbow Mode';
          inputs.forEach(input => input.classList.replace('pink', 'rainbow'));
          ths.forEach(th => th.classList.replace('pink', 'rainbow'));
          tds.forEach(td => td.classList.replace('pink', 'rainbow'));
        } else if (body.classList.contains('rainbow')) {
          body.classList.replace('rainbow', 'dark');
          container.classList.replace('rainbow', 'dark');
          h1.classList.replace('rainbow', 'dark');
          status.classList.replace('rainbow', 'dark');
          themeToggle.classList.replace('rainbow', 'dark');
          themeToggle.textContent = '🌑 Dark Mode';
          inputs.forEach(input => input.classList.replace('rainbow', 'dark'));
          ths.forEach(th => th.classList.replace('rainbow', 'dark'));
          tds.forEach(td => td.classList.replace('rainbow', 'dark'));
        }
      }

      function showLoginForm() {
        document.getElementById('loginForm').style.display = 'block';
        document.getElementById('dashboard').style.display = 'none';
        document.getElementById('buttoncontainer').style.display = 'none';
      }

      function showDashboard() {
        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('dashboard').style.display = 'block';
        document.getElementById('buttoncontainer').style.display = 'block';
        fetchResults();
      }

      async function checkAuth() {
        const response = await fetch('/check-auth');
        const data = await response.json();
        if (data.authenticated) {
          showDashboard();
        } else {
          showLoginForm();
        }
      }

      async function login() {
        password = document.getElementById('password').value;
        const formData = new FormData();
        formData.append('password', password);
        const response = await fetch('/login', { 
          method: 'POST',
          body: formData
        });
        const result = await response.json();
        if (result.success) {
          showDashboard();
        } else {
          alert('Incorrect password');
        }
      }

      async function runScript() {
        const statusDiv = document.getElementById('status');
        statusDiv.textContent = 'Executing script...';
        try {
          const response = await fetch('/run', { method: 'POST' });
          if (response.ok) {
            const results = await response.json();
            displayResults(results);
            statusDiv.textContent = 'Script executed successfully!';
          } else if (response.status === 401) {
            statusDiv.textContent = 'Unauthorized. Please login again.';
            showLoginForm();
          } else {
            statusDiv.textContent = 'Error executing script.';
          }
        } catch (error) {
          statusDiv.textContent = 'Error: ' + error.message;
        }
      }

      async function fetchResults() {
        try {
          const response = await fetch('/results');
          if (response.ok) {
            const data = await response.json();
            if (data.authenticated) {
              displayResults(data.results);
            } else {
              showLoginForm();
            }
          } else {
            console.error('Failed to fetch results');
            showLoginForm();
          }
        } catch (error) {
          console.error('Error fetching results:', error);
          showLoginForm();
        }
      }

      function displayResults(results) {
        const tbody = document.querySelector('#resultsTable tbody');
        tbody.innerHTML = '';
        results.forEach(result => {
          result.cronResults.forEach((cronResult, index) => {
            const row = tbody.insertRow();
            if (index === 0) {
              row.insertCell(0).textContent = result.username;
              row.insertCell(1).textContent = result.type;
            } else {
              row.insertCell(0).textContent = '';
              row.insertCell(1).textContent = '';
            }
            row.insertCell(2).textContent = cronResult.success ? 'Success' : 'Failed';
            row.cells[2].className = cronResult.success ? 'success' : 'failed';
            row.insertCell(3).textContent = cronResult.message;
            row.insertCell(4).textContent = new Date(result.lastRun).toLocaleString();
          });
        });
      }

      // 页面加载时检查认证状态
      document.addEventListener('DOMContentLoaded', checkAuth);
    </script>
  </body>
  <footer>
  <font color=#FB09F4> </font><font color=#F712E9>p</font><font color=#F31BDE>o</font><font color=#EF24D3>w</font><font color=#EB2DC8>e</font><font color=#E736BD>r</font><font color=#E33FB2>e</font><font color=#DF48A7>d</font><font color=#DB519C> </font><font color=#D75A91>b</font><font color=#D36386>y</font><font color=#CF6C7B> </font><font color=#CB7570>c</font><font color=#C77E65>l</font><font color=#C3875A>o</font><font color=#BF904F>u</font><font color=#BB9944>d</font><font color=#B7A239>f</font><font color=#B3AB2E>l</font><font color=#AFB423>a</font><font color=#ABBD18>r</font><font color=#A7C60D>e</font>
    <svg xmlns="http://www.w3.org/2000/svg" id="Layer_2" viewBox="0 0 109 40.5"><style><script xmlns=""/>.st0{fill:#fff}.st1{fill:#f48120}.st2{fill:#faad3f}.st3{fill:#404041}</style><path class="st0" d="M98.6 14.2L93 12.9l-1-.4-25.7.2v12.4l32.3.1z"/><path class="st1" d="M88.1 24c.3-1 .2-2-.3-2.6-.5-.6-1.2-1-2.1-1.1l-17.4-.2c-.1 0-.2-.1-.3-.1-.1-.1-.1-.2 0-.3.1-.2.2-.3.4-.3l17.5-.2c2.1-.1 4.3-1.8 5.1-3.8l1-2.6c0-.1.1-.2 0-.3-1.1-5.1-5.7-8.9-11.1-8.9-5 0-9.3 3.2-10.8 7.7-1-.7-2.2-1.1-3.6-1-2.4.2-4.3 2.2-4.6 4.6-.1.6 0 1.2.1 1.8-3.9.1-7.1 3.3-7.1 7.3 0 .4 0 .7.1 1.1 0 .2.2.3.3.3h32.1c.2 0 .4-.1.4-.3l.3-1.1z"/><path class="st2" d="M93.6 12.8h-.5c-.1 0-.2.1-.3.2l-.7 2.4c-.3 1-.2 2 .3 2.6.5.6 1.2 1 2.1 1.1l3.7.2c.1 0 .2.1.3.1.1.1.1.2 0 .3-.1.2-.2.3-.4.3l-3.8.2c-2.1.1-4.3 1.8-5.1 3.8l-.2.9c-.1.1 0 .3.2.3h13.2c.2 0 .3-.1.3-.3.2-.8.4-1.7.4-2.6 0-5.2-4.3-9.5-9.5-9.5"/><path class="st3" d="M104.4 30.8c-.5 0-.9-.4-.9-.9s.4-.9.9-.9.9.4.9.9-.4.9-.9.9m0-1.6c-.4 0-.7.3-.7.7 0 .4.3.7.7.7.4 0 .7-.3.7-.7 0-.4-.3-.7-.7-.7m.4 1.2h-.2l-.2-.3h-.2v.3h-.2v-.9h.5c.2 0 .3.1.3.3 0 .1-.1.2-.2.3l.2.3zm-.3-.5c.1 0 .1 0 .1-.1s-.1-.1-.1-.1h-.3v.3h.3zM14.8 29H17v6h3.8v1.9h-6zm8.3 3.9c0-2.3 1.8-4.1 4.3-4.1s4.2 1.8 4.2 4.1-1.8 4.1-4.3 4.1c-2.4 0-4.2-1.8-4.2-4.1m6.3 0c0-1.2-.8-2.2-2-2.2s-2 1-2 2.1.8 2.1 2 2.1c1.2.2 2-.8 2-2m4.9.5V29h2.2v4.4c0 1.1.6 1.7 1.5 1.7s1.5-.5 1.5-1.6V29h2.2v4.4c0 2.6-1.5 3.7-3.7 3.7-2.3-.1-3.7-1.2-3.7-3.7M45 29h3.1c2.8 0 4.5 1.6 4.5 3.9s-1.7 4-4.5 4h-3V29zm3.1 5.9c1.3 0 2.2-.7 2.2-2s-.9-2-2.2-2h-.9v4h.9zm7.6-5.9H62v1.9h-4.1v1.3h3.7V34h-3.7v2.9h-2.2zm9.4 0h2.2v6h3.8v1.9h-6zm11.7-.1H79l3.4 8H80l-.6-1.4h-3.1l-.6 1.4h-2.3l3.4-8zm2 4.9l-.9-2.2-.9 2.2h1.8zm6.4-4.8h3.7c1.2 0 2 .3 2.6.9.5.5.7 1.1.7 1.8 0 1.2-.6 2-1.6 2.4l1.9 2.8H90l-1.6-2.4h-1v2.4h-2.2V29zm3.6 3.8c.7 0 1.2-.4 1.2-.9 0-.6-.5-.9-1.2-.9h-1.4v1.9h1.4zm6.5-3.8h6.4v1.8h-4.2V32h3.8v1.8h-3.8V35h4.3v1.9h-6.5zM10 33.9c-.3.7-1 1.2-1.8 1.2-1.2 0-2-1-2-2.1s.8-2.1 2-2.1c.9 0 1.6.6 1.9 1.3h2.3c-.4-1.9-2-3.3-4.2-3.3-2.4 0-4.3 1.8-4.3 4.1s1.8 4.1 4.2 4.1c2.1 0 3.7-1.4 4.2-3.2H10z"/></svg>
  </footer>
  </html>
  `;
}
async function handleScheduled(scheduledTime) {
  const accountsData = JSON.parse(ACCOUNTS_JSON);
  const accounts = accountsData.accounts;

  let results = [];
  for (const account of accounts) {
    const result = await loginAccount(account);
    results.push(result);
    await delay(Math.floor(Math.random() * 8000) + 1000);
  }

  // 保存结果到 KV 存储
  await CRON_RESULTS.put('lastResults', JSON.stringify(results));
}

function generateRandomUserAgent() {
  const browsers = ['Chrome', 'Firefox', 'Safari', 'Edge', 'Opera'];
  const browser = browsers[Math.floor(Math.random() * browsers.length)];
  const version = Math.floor(Math.random() * 100) + 1;
  const os = ['Windows NT 10.0', 'Macintosh', 'X11'];
  const selectedOS = os[Math.floor(Math.random() * os.length)];
  const osVersion = selectedOS === 'X11' ? 'Linux x86_64' : selectedOS === 'Macintosh' ? 'Intel Mac OS X 10_15_7' : 'Win64; x64';

  return `Mozilla/5.0 (${selectedOS}; ${osVersion}) AppleWebKit/537.36 (KHTML, like Gecko) ${browser}/${version}.0.0.0 Safari/537.36`;
}

async function loginAccount(account) {
  const { username, password, panelnum, type, cronCommands } = account
  let baseUrl = type === 'ct8'
    ? 'https://panel.ct8.pl'
    : `https://panel${panelnum}.serv00.com`
  let loginUrl = `${baseUrl}/login/?next=/cron/`

  const userAgent = generateRandomUserAgent();

  try {
    const response = await fetch(loginUrl, {
      method: 'GET',
      headers: {
        'User-Agent': userAgent,
      },
    })

    const pageContent = await response.text()
    const csrfMatch = pageContent.match(/name="csrfmiddlewaretoken" value="([^"]*)"/)
    const csrfToken = csrfMatch ? csrfMatch[1] : null

    if (!csrfToken) {
      throw new Error('CSRF token not found')
    }

    const initialCookies = response.headers.get('set-cookie') || ''

    const formData = new URLSearchParams({
      'username': username,
      'password': password,
      'csrfmiddlewaretoken': csrfToken,
      'next': '/cron/'
    })

    const loginResponse = await fetch(loginUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': loginUrl,
        'User-Agent': userAgent,
        'Cookie': initialCookies,
      },
      body: formData.toString(),
      redirect: 'manual'
    })

    if (loginResponse.status === 302 && loginResponse.headers.get('location') === '/cron/') {
      const loginCookies = loginResponse.headers.get('set-cookie') || ''
      const allCookies = combineCookies(initialCookies, loginCookies)

      // 访问 cron 列表页面
      const cronListUrl = `${baseUrl}/cron/`
      const cronListResponse = await fetch(cronListUrl, {
        headers: {
          'Cookie': allCookies,
          'User-Agent': userAgent,
        }
      })
      const cronListContent = await cronListResponse.text()

      console.log(`Cron list URL: ${cronListUrl}`)
      console.log(`Cron list response status: ${cronListResponse.status}`)
      console.log(`Cron list content (first 1000 chars): ${cronListContent.substring(0, 1000)}`)

      let cronResults = [];
      for (const cronCommand of cronCommands) {
        if (!cronListContent.includes(cronCommand)) {
          // 访问添加 cron 任务页面
          const addCronUrl = `${baseUrl}/cron/add`
          const addCronPageResponse = await fetch(addCronUrl, {
            headers: {
              'Cookie': allCookies,
              'User-Agent': userAgent,
              'Referer': cronListUrl,
            }
          })
          const addCronPageContent = await addCronPageResponse.text()

          console.log(`Add cron page URL: ${addCronUrl}`)
          console.log(`Add cron page response status: ${addCronPageResponse.status}`)
          console.log(`Add cron page content (first 1000 chars): ${addCronPageContent.substring(0, 1000)}`)

          const newCsrfMatch = addCronPageContent.match(/name="csrfmiddlewaretoken" value="([^"]*)"/)
          const newCsrfToken = newCsrfMatch ? newCsrfMatch[1] : null

          if (!newCsrfToken) {
            throw new Error('New CSRF token not found for adding cron task')
          }

          const formData = new URLSearchParams({
            'csrfmiddlewaretoken': newCsrfToken,
            'spec': 'manual',
            'minute_time_interval': 'on',
            'minute': '15',
            'hour_time_interval': 'each',
            'hour': '*',
            'day_time_interval': 'each',
            'day': '*',
            'month_time_interval': 'each',
            'month': '*',
            'dow_time_interval': 'each',
            'dow': '*',
            'command': cronCommand,
            'comment': 'Auto added cron job'
          })

          console.log('Form data being sent:', formData.toString())

          const { success, response: addCronResponse, content: addCronResponseContent } = await addCronWithRetry(addCronUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded',
              'Cookie': allCookies,
              'User-Agent': userAgent,
              'Referer': addCronUrl,
              'Origin': baseUrl,
              'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
              'Accept-Language': 'en-US,en;q=0.5',
              'Upgrade-Insecure-Requests': '1'
            },
            body: formData.toString(),
          })

          console.log('Full response content:', addCronResponseContent)

          if (success) {
            if (addCronResponseContent.includes('Cron job has been added') || addCronResponseContent.includes('Zadanie cron zostało dodane')) {
              const message = `添加了新的 cron 任务：${cronCommand}`;
              console.log(message);
              await sendTelegramMessage(`账号 ${username} (${type}) ${message}`);
              cronResults.push({ success: true, message });
            } else {
              // 如果响应中没有成功信息，再次检查cron列表
              const checkCronListResponse = await fetch(cronListUrl, {
                headers: {
                  'Cookie': allCookies,
                  'User-Agent': userAgent,
                }
              });
              const checkCronListContent = await checkCronListResponse.text();

              if (checkCronListContent.includes(cronCommand)) {
                const message = `确认添加了新的 cron 任务：${cronCommand}`;
                console.log(message);
                await sendTelegramMessage(`账号 ${username} (${type}) ${message}`);
                cronResults.push({ success: true, message });
              } else {
                const message = `尝试添加 cron 任务：${cronCommand}，但在列表中未找到。可能添加失败。`;
                console.error(message);
                cronResults.push({ success: false, message });
              }
            }
          } else {
            const message = `添加 cron 任务失败：${cronCommand}`;
            console.error(message);
            cronResults.push({ success: false, message });
          }
        } else {
          const message = `cron 任务已存在：${cronCommand}`;
          console.log(message);
          cronResults.push({ success: true, message });
        }
      }
      return { username, type, cronResults, lastRun: new Date().toISOString() };
    } else {
      const message = `登录失败，未知原因。请检查账号和密码是否正确。`;
      console.error(message);
      return { username, type, cronResults: [{ success: false, message }], lastRun: new Date().toISOString() };
    }
  } catch (error) {
    const message = `登录或添加 cron 任务时出现错误: ${error.message}`;
    console.error(message);
    return { username, type, cronResults: [{ success: false, message }], lastRun: new Date().toISOString() };
  }
}

async function addCronWithRetry(url, options, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await fetch(url, options);
      const responseContent = await response.text();
      console.log(`Attempt ${i + 1} response status:`, response.status);
      console.log(`Attempt ${i + 1} response content (first 1000 chars):`, responseContent.substring(0, 1000));

      if (response.status === 200 || response.status === 302 || responseContent.includes('Cron job has been added') || responseContent.includes('Zadanie cron zostało dodane')) {
        return { success: true, response, content: responseContent };
      }
    } catch (error) {
      console.error(`Attempt ${i + 1} failed:`, error);
    }
    await delay(2000); // Wait 2 seconds before retrying
  }
  return { success: false };
}

function combineCookies(cookies1, cookies2) {
  const cookieMap = new Map()

  const parseCookies = (cookieString) => {
    cookieString.split(',').forEach(cookie => {
      const [fullCookie] = cookie.trim().split(';')
      const [name, value] = fullCookie.split('=')
      if (name && value) {
        cookieMap.set(name.trim(), value.trim())
      }
    })
  }

  parseCookies(cookies1)
  parseCookies(cookies2)

  return Array.from(cookieMap.entries()).map(([name, value]) => `${name}=${value}`).join('; ')
}

async function sendTelegramMessage(message) {
  const telegramConfig = JSON.parse(TELEGRAM_JSON)
  const { telegramBotToken, telegramBotUserId } = telegramConfig
  const url = `https://api.telegram.org/bot${telegramBotToken}/sendMessage`

  try {
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: telegramBotUserId,
        text: message
      })
    })
  } catch (error) {
    console.error('Error sending Telegram message:', error)
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
