const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let page = 1;
const say = (text) => { $('message').textContent = text; };
async function api(url, options = {}) {
  const response = await fetch(url, {...options, headers: {'X-CSRF-Token': csrf, ...(options.headers || {})}});
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
  return body;
}
function button(text, callback) {
  const element = document.createElement('button'); element.textContent = text;
  element.className = 'secondary'; element.type = 'button';
  element.addEventListener('click', async () => { try { await callback(); } catch (e) { say(e.message); } });
  return element;
}
function resetForm() { $('vehicle-form').reset(); $('vehicle-id').value = ''; }
async function loadVehicles() {
  const data = await api(`/api/vehicles?q=${encodeURIComponent($('search').value)}&page=${page}`);
  $('vehicles').replaceChildren(); $('page').textContent = `第${page}页`;
  $('previous').disabled = page <= 1; $('next').disabled = data.records.length < 50;
  for (const item of data.records) {
    const row = document.createElement('tr');
    for (const key of ['plate', 'vehicle_type', 'note']) {
      const td = document.createElement('td'); td.textContent = item[key]; row.append(td);
    }
    const actions = document.createElement('td');
    actions.append(button('修改', () => {
      $('vehicle-id').value = item.id; $('plate').value = item.plate;
      $('vehicle-type').value = item.vehicle_type; $('note').value = item.note; $('plate').focus();
    }), button('删除', async () => {
      if (!confirm(`删除车辆 ${item.plate}？`)) return;
      await api(`/api/vehicles/${item.id}`, {method: 'DELETE'}); await loadVehicles();
    })); row.append(actions); $('vehicles').append(row);
  }
  if (!data.records.length) { const row = $('vehicles').insertRow(); const cell = row.insertCell(); cell.colSpan = 4; cell.textContent = '暂无记录'; }
}
async function loadHistory() {
  const data = await api('/api/detections'); $('history').replaceChildren();
  for (const item of data.records) {
    const card = document.createElement('div'); card.className = 'history-card';
    const image = document.createElement('img'); image.src = item.image_url; image.alt = '历史检测结果';
    const text = document.createElement('p'); text.textContent = `${new Date(item.created_at).toLocaleString()} · ${item.count} 个目标`;
    const link = document.createElement('a'); link.href = item.image_url; link.target = '_blank'; link.rel = 'noopener'; link.append(image);
    card.append(link, text, button('删除', async () => {
      if (!confirm('删除这条检测记录及结果图片？')) return;
      await api(`/api/detections/${item.id}`, {method: 'DELETE'}); await loadHistory();
    })); $('history').append(card);
  }
  if (!data.records.length) $('history').textContent = '暂无检测记录';
}
$('detect-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  say('正在检测；首次使用可能需要下载模型，请稍候。');
  try {
    const data = await api('/api/detect', {method: 'POST', body: new FormData(event.target)});
    $('result-image').src = data.image_url; $('result-image').hidden = false;
    $('summary').textContent = `检测到 ${data.count} 个目标`; say('检测完成，记录已保存。'); await loadHistory();
  } catch (error) { say(error.message); } finally { submit.disabled = false; }
});
$('vehicle-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const id = $('vehicle-id').value;
  try {
    await api('/api/vehicles' + (id ? `/${id}` : ''), {method: id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({plate:$('plate').value, vehicle_type:$('vehicle-type').value, note:$('note').value})});
    resetForm(); await loadVehicles(); say('车辆记录已保存。');
  } catch (error) { say(error.message); }
});
$('cancel-edit').addEventListener('click', resetForm);
$('search-form').addEventListener('submit', (event) => { event.preventDefault(); page = 1; loadVehicles().catch(e => say(e.message)); });
$('previous').addEventListener('click', () => { if (page > 1) page--; loadVehicles().catch(e => say(e.message)); });
$('next').addEventListener('click', () => { page++; loadVehicles().catch(e => say(e.message)); });
$('refresh').addEventListener('click', () => loadHistory().catch(e => say(e.message)));
$('camera-start').addEventListener('click', () => { $('camera-image').hidden = false; $('camera-image').src = `/video_feed?t=${Date.now()}`; });
$('camera-stop').addEventListener('click', () => { $('camera-image').removeAttribute('src'); $('camera-image').hidden = true; });
$('camera-image').addEventListener('error', () => say('摄像头预览未能启动，请检查设备、模型依赖及服务端日志。'));
Promise.all([loadVehicles(), loadHistory()]).catch(e => say(e.message));
