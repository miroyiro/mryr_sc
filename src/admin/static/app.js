// 관리 GUI (바닐라 JS, 빌드 없음).
// 규칙: 서버 응답·사용자 입력은 전부 textContent 로만 넣는다 (innerHTML 금지 → XSS 차단).
//       오류 화면에는 고정 문구만. 서버 에러 본문·stack 은 화면에 절대 안 그림.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { me: null, view: "dashboard", page: 1, limit: 20, total: 0, retry: null };

class AuthError extends Error {}   // 401 → 로그인 화면으로
class LoadError extends Error {}   // 5xx·네트워크 → 고정 오류 문구 + 다시 시도

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && state.me && state.me.csrf_token) headers["X-CSRF-Token"] = state.me.csrf_token;
  let resp;
  try {
    resp = await fetch("/admin/api" + path, {
      method, headers, credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (_) {
    throw new LoadError();               // 네트워크 실패
  }
  if (resp.status === 401) throw new AuthError();
  if (resp.status >= 500) throw new LoadError();
  const data = resp.status === 204 ? null : await resp.json().catch(() => null);
  return { status: resp.status, data };
}

// --- 화면 상태 ---
function showOnly(viewId) {
  for (const id of ["view-login", "view-dashboard", "view-sources", "view-targets"]) $(id).hidden = id !== viewId;
  for (const b of document.querySelectorAll("#nav button")) b.classList.toggle("active", "view-" + b.dataset.view === viewId);
}
function setLoading(on) { $("loading").hidden = !on; if (on) $("error").hidden = true; }
function showError(retryFn) {
  setLoading(false);
  state.retry = retryFn;
  for (const id of ["view-dashboard", "view-sources", "view-targets"]) $(id).hidden = true;
  $("error").hidden = false;
}

function renderHeader() {
  const authed = !!(state.me && state.me.authenticated);
  document.body.classList.toggle("authed", authed);
  $("who-name").textContent = authed ? state.me.username + " (" + state.me.role + ")" : "비로그인 열람";
  $("btn-logout").hidden = !authed;
  $("btn-login").hidden = authed;
  $("nav").hidden = !(authed || (state.me && state.me.public_read));
}

function showLogin(message) {
  setLoading(false);
  $("error").hidden = true;
  $("nav").hidden = true;
  $("login-msg").textContent = message || "";
  showOnly("view-login");
}

// --- DOM 도우미 (textContent 만) ---
function fmt(iso) {
  return iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "-";
}
function row(cells, onClick) {
  const tr = document.createElement("tr");
  for (const c of cells) {
    const td = document.createElement("td");
    td.textContent = c === null || c === undefined ? "-" : String(c);
    tr.appendChild(td);
  }
  if (onClick) { tr.classList.add("clickable"); tr.addEventListener("click", onClick); }
  return tr;
}
function emptyRow(colspan, text) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.textContent = text;
  tr.appendChild(td);
  return tr;
}
const authed = () => !!(state.me && state.me.authenticated);

// --- 뷰 ---
async function loadDashboard() {
  const { data } = await api("/dashboard");
  const started = fmt(data.started_at);
  $("dash-started").textContent = started;
  const total = data.source_counts.reduce((a, s) => a + s.collected, 0);
  $("dash-empty").hidden = !(total === 0 && data.recent_jobs.length === 0);
  $("dash-empty").textContent = "수집 준비 중, 가동 시작 시각: " + started;

  $("dash-counts").replaceChildren(...(data.source_counts.length
    ? data.source_counts.map((s) => row([s.source_name, s.collected]))
    : [emptyRow(2, "등록된 소스가 없습니다")]));
  $("dash-jobs").replaceChildren(...(data.recent_jobs.length
    ? data.recent_jobs.map((j) => row([j.id, j.source_name, j.status, j.collected_count, j.duplicate_count,
        j.error_count, fmt(j.started_at), fmt(j.finished_at)]))
    : [emptyRow(8, "아직 실행된 잡이 없습니다")]));

  const errs = data.error_counts;   // 로그인 응답에만 있음
  $("dash-errors-wrap").hidden = !errs;
  if (errs) {
    $("dash-errors").replaceChildren(...(errs.length
      ? errs.map((e) => row([e.type, e.count])) : [emptyRow(2, "미해결 에러 없음")]));
  }
}

async function loadSources() {
  const { data } = await api("/sources");
  $("sources-body").replaceChildren(...(data.length
    ? data.map((s) => {
        const cells = [s.name, s.type, s.enabled ? "켜짐" : "꺼짐", s.last_job_status || "-"];
        if (authed()) cells.push(s.monthly_budget_usd ?? "미설정");
        return row(cells);
      })
    : [emptyRow(5, "수집 준비 중")]));
}

async function loadTargets() {
  const { data } = await api("/targets?page=" + state.page + "&limit=" + state.limit);
  state.total = data.meta.total;
  $("target-detail").hidden = true;
  $("targets-body").replaceChildren(...(data.data.length
    ? data.data.map((t) => {
        const label = authed() ? t.value : (t.handle || "(비공개)");
        const cells = [t.id, t.source_name, t.target_type, label, t.status];
        if (authed()) cells.push(t.is_verified ? "검증됨" : "미검증");
        return row(cells, () => openTarget(t.id));
      })
    : [emptyRow(6, "등록된 수집 대상이 없습니다")]));
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  $("page-info").textContent = state.page + " / " + pages;
  $("btn-prev").disabled = state.page <= 1;
  $("btn-next").disabled = state.page >= pages;
}

const DETAIL_LABELS = {
  id: "ID", source_name: "소스", target_type: "타입", handle: "X 핸들", value: "값", status: "상태",
  is_verified: "검증", crawl_interval_sec: "수집 간격(초)", last_crawled_at: "마지막 수집",
  admin_note: "메모", verified_by: "검증자 ID", verified_at: "검증 시각", created_at: "등록",
};

async function openTarget(id) {
  try {
    const { status, data } = await api("/targets/" + encodeURIComponent(id));
    if (status !== 200) return;
    const items = [];
    for (const [key, label] of Object.entries(DETAIL_LABELS)) {
      if (!(key in data)) continue;
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd");
      const v = data[key];
      dd.textContent = key.endsWith("_at") ? fmt(v) : v === null ? "-" : String(v);
      items.push(dt, dd);
    }
    $("target-detail-list").replaceChildren(...items);
    $("target-detail").hidden = false;
    renderEdit(data);
  } catch (e) {
    handleFailure(e, () => openTarget(id));
  }
}

// --- 쓰기 (메모·verify). 버튼 숨김은 편의일 뿐, 권한은 서버가 매번 검사 ---
function renderEdit(t) {
  state.targetId = t.id;
  $("target-edit").hidden = !authed();
  if (!authed()) return;
  $("note-input").value = t.admin_note || "";     // value 는 텍스트로만 들어감 (HTML 해석 X)
  $("btn-verify").hidden = !(state.me.role === "admin" && t.target_type === "x_account" && !t.is_verified);
  setEditMsg("");
}

function setEditMsg(text, ok) {
  $("edit-msg").textContent = text;
  $("edit-msg").classList.toggle("ok", !!ok);
}

const WRITE_ERRORS = {
  400: "이 대상은 여기서 검증할 수 없습니다 (X 계정만)",
  403: "권한이 없거나 세션이 바뀌었습니다. 새로고침 후 다시 시도해 주세요",
  404: "대상을 찾을 수 없습니다",
  409: "이 소스의 월 예산(monthly_budget_usd)이 설정되지 않아 검증할 수 없습니다",
  422: "입력값을 확인해 주세요 (메모는 500자까지)",
};

async function write(path, options, doneText) {
  const id = state.targetId;
  try {
    const { status } = await api(path, options);
    if (status === 200) {
      await openTarget(id);          // 서버가 저장한 값으로 다시 그림
      setEditMsg(doneText, true);
    } else {
      setEditMsg(WRITE_ERRORS[status] || "저장하지 못했습니다. 잠시 후 다시 시도해 주세요");
    }
  } catch (e) {
    if (e instanceof AuthError) return handleFailure(e);
    setEditMsg("저장하지 못했습니다. 잠시 후 다시 시도해 주세요");   // 5xx·네트워크: 고정 문구만
  }
}

const LOADERS = { dashboard: loadDashboard, sources: loadSources, targets: loadTargets };

function handleFailure(e, retryFn) {
  if (e instanceof AuthError) {
    // PUBLIC_READ=false 이거나 세션 만료 → 로그인 화면
    state.me = { authenticated: false, public_read: state.me ? state.me.public_read : false };
    renderHeader();
    showLogin("로그인이 필요합니다");
  } else {
    showError(retryFn);
  }
}

async function go(view) {
  state.view = view;
  setLoading(true);
  try {
    await LOADERS[view]();
    setLoading(false);
    showOnly("view-" + view);
  } catch (e) {
    handleFailure(e, () => go(view));
  }
}

async function boot() {
  setLoading(true);
  try {
    state.me = (await api("/me")).data;
  } catch (e) {
    return showError(boot);
  }
  renderHeader();
  if (!state.me.authenticated && !state.me.public_read) return showLogin();
  go(state.view);
}

// --- 이벤트 ---
document.addEventListener("DOMContentLoaded", () => {
  for (const b of document.querySelectorAll("#nav button")) b.addEventListener("click", () => go(b.dataset.view));
  $("btn-retry").addEventListener("click", () => state.retry && state.retry());
  $("btn-login").addEventListener("click", () => showLogin());
  $("btn-prev").addEventListener("click", () => { state.page -= 1; go("targets"); });
  $("btn-next").addEventListener("click", () => { state.page += 1; go("targets"); });

  $("btn-note-save").addEventListener("click", () =>
    write("/targets/" + encodeURIComponent(state.targetId) + "/note",
      { method: "PATCH", body: { admin_note: $("note-input").value } }, "메모를 저장했습니다"));

  $("btn-verify").addEventListener("click", () => {
    if (!window.confirm("이 X 계정을 검증하면 수집이 시작됩니다(유료 API). 진행할까요?")) return;
    write("/targets/" + encodeURIComponent(state.targetId) + "/verify", { method: "POST" }, "검증했습니다");
  });

  $("btn-logout").addEventListener("click", async () => {
    try { await api("/logout", { method: "POST" }); } catch (_) { /* 실패해도 화면은 초기화 */ }
    state.me = null;
    boot();
  });

  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    $("login-msg").textContent = "";
    try {
      const { status, data } = await api("/login", {
        method: "POST", body: { username: f.username.value, password: f.password.value },
      });
      f.password.value = "";
      if (status === 200) { state.me = data; renderHeader(); go("dashboard"); return; }
      $("login-msg").textContent = status === 429
        ? "로그인 시도가 너무 많습니다. 15분 뒤 다시 시도해 주세요" : "아이디 또는 비밀번호가 올바르지 않습니다";
    } catch (e) {
      f.password.value = "";
      $("login-msg").textContent = e instanceof AuthError
        ? "아이디 또는 비밀번호가 올바르지 않습니다" : "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요";
    }
  });

  boot();
});
