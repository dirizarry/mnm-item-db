import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const FLOOR_HEIGHT = 6;
const LOOT_COLORS = {
  cloth: 0xd4a85a,
  chain: 0x5eb8c9,
  plate: 0x9a7ad4,
  leather: 0x7ab86a,
};
const CONN_COLORS = {
  zone_line: 0xe0b86a,
  stair: 0x8ab4d4,
  stair_down: 0x6a94b4,
  overpass: 0xc87830,
  pit_trap: 0xc45c4a,
  tunnel: 0x9a7ad4,
};

const els = {};
const state = {
  zone: null,
  viewMode: "exploded",
  activeFloor: null,
  selectedPoi: null,
  selectedConn: null,
  route: [],
  roomMeshes: new Map(),
  poiMeshes: new Map(),
  connLines: new Map(),
  floorGroups: new Map(),
};

let scene, camera, renderer, controls, raycaster, mouse;
let animId = null;

async function init() {
  cacheEls();
  const res = await fetch("data/wyrmsbane-tomb.json");
  state.zone = await res.json();
  bindUi();
  setupThree();
  buildZone();
  renderSidebar();
  animate();
  fitCamera();
}

function cacheEls() {
  els.viewport = document.getElementById("viewport");
  els.tooltip = document.getElementById("tooltip");
  els.hudTitle = document.getElementById("hud-title");
  els.hudDetail = document.getElementById("hud-detail");
  els.floorList = document.getElementById("floor-list");
  els.poiList = document.getElementById("poi-list");
  els.connList = document.getElementById("conn-list");
  els.routeList = document.getElementById("route-list");
  els.zoneTitle = document.getElementById("zone-title");
}

function bindUi() {
  els.zoneTitle.textContent = state.zone.name;

  document.querySelectorAll("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => setViewMode(btn.dataset.view));
  });

  document.getElementById("btn-fit").addEventListener("click", fitCamera);
  document.getElementById("btn-route-clear").addEventListener("click", clearRoute);

  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => loadPreset(btn.dataset.preset));
  });

  els.viewport.addEventListener("pointermove", onPointerMove);
  els.viewport.addEventListener("click", onClick);
  window.addEventListener("resize", onResize);
}

function setupThree() {
  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0908, 0.012);

  const wrap = els.viewport.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;

  camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 500);
  camera.position.set(35, 42, 45);

  renderer = new THREE.WebGLRenderer({ canvas: els.viewport, antialias: true });
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;

  controls = new OrbitControls(camera, els.viewport);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.maxPolarAngle = Math.PI * 0.48;
  controls.minDistance = 10;
  controls.maxDistance = 120;

  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  const amb = new THREE.AmbientLight(0x6a6050, 0.55);
  scene.add(amb);

  const sun = new THREE.DirectionalLight(0xffeed8, 0.9);
  sun.position.set(30, 60, 20);
  sun.castShadow = true;
  scene.add(sun);

  const fill = new THREE.DirectionalLight(0x5eb8c9, 0.25);
  fill.position.set(-20, 30, -10);
  scene.add(fill);

  const grid = new THREE.GridHelper(80, 40, 0x2a2318, 0x1a1610);
  grid.position.y = -0.5;
  scene.add(grid);
}

function floorY(index, mode) {
  if (mode === "compact") return index * 1.2;
  if (mode === "single") return 0;
  return index * (state.zone.floorGap || FLOOR_HEIGHT);
}

function floorVisible(floorId, mode) {
  if (mode !== "single" || !state.activeFloor) return true;
  return floorId === state.activeFloor;
}

function roomCenter(room) {
  return new THREE.Vector3(room.x + room.w / 2, 0, room.z + room.d / 2);
}

function getRoom(floorId, roomId) {
  const floor = state.zone.floors.find((f) => f.id === floorId);
  return floor?.rooms.find((r) => r.id === roomId) || null;
}

function buildZone() {
  state.zone.floors.forEach((floor, fi) => {
    const group = new THREE.Group();
    group.userData = { floorId: floor.id };
    state.floorGroups.set(floor.id, group);
    group.visible = floorVisible(floor.id, state.viewMode);

    const y = floorY(fi, state.viewMode);
    group.position.y = y;

    const slab = new THREE.Mesh(
      new THREE.BoxGeometry(42, 0.15, 42),
      new THREE.MeshStandardMaterial({
        color: 0x14110d,
        roughness: 0.95,
        metalness: 0.05,
        transparent: true,
        opacity: 0.35,
      })
    );
    slab.position.set(2, -0.2, -4);
    slab.receiveShadow = true;
    group.add(slab);

    const floorColor = new THREE.Color(floor.color);

    floor.rooms.forEach((room) => {
      const geo = new THREE.BoxGeometry(room.w, room.h || 0.5, room.d);
      const mat = new THREE.MeshStandardMaterial({
        color: floorColor,
        roughness: 0.75,
        metalness: 0.1,
        emissive: floorColor,
        emissiveIntensity: 0.08,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(room.x + room.w / 2, (room.h || 0.5) / 2, room.z + room.d / 2);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData = {
        type: "room",
        floorId: floor.id,
        roomId: room.id,
        name: room.name,
      };
      group.add(mesh);
      state.roomMeshes.set(`${floor.id}:${room.id}`, mesh);

      const edge = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0x463a26, transparent: true, opacity: 0.6 })
      );
      edge.position.copy(mesh.position);
      group.add(edge);
    });

    scene.add(group);
  });

  state.zone.pois.forEach((poi) => {
    const room = getRoom(poi.floor, poi.room);
    if (!room) return;
    const fi = state.zone.floors.findIndex((f) => f.id === poi.floor);
    const y = floorY(fi, state.viewMode) + (room.h || 0.5) + 0.6;
    const visible = floorVisible(poi.floor, state.viewMode);
    const cx = room.x + room.w / 2;
    const cz = room.z + room.d / 2;

    const color = LOOT_COLORS[poi.loot] || 0xd9b46a;
    const geo = new THREE.SphereGeometry(0.55, 16, 16);
    const mat = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.45,
      roughness: 0.4,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(cx, y, cz);
    mesh.userData = { type: "poi", poiId: poi.id, poi };
    mesh.visible = visible;
    scene.add(mesh);
    state.poiMeshes.set(poi.id, mesh);

    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.7, 0.85, 24),
      new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.5 })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(cx, y - 0.5, cz);
    ring.visible = visible;
    scene.add(ring);
    mesh.userData.ring = ring;
  });

  state.zone.connections.forEach((conn) => buildConnection(conn));
}

function buildConnection(conn) {
  const from = conn.from;
  if (!from) return;

  const fromRoom = getRoom(from.floor, from.room);
  if (!fromRoom) return;

  const fromFi = state.zone.floors.findIndex((f) => f.id === from.floor);
  const fromPos = roomCenter(fromRoom);
  fromPos.y = floorY(fromFi, state.viewMode) + 1;
  const fromVis = floorVisible(from.floor, state.viewMode);

  let toPos;
  let toVis = true;
  if (conn.to) {
    const toRoom = getRoom(conn.to.floor, conn.to.room);
    if (!toRoom) return;
    const toFi = state.zone.floors.findIndex((f) => f.id === conn.to.floor);
    toPos = roomCenter(toRoom);
    toPos.y = floorY(toFi, state.viewMode) + 1;
    toVis = floorVisible(conn.to.floor, state.viewMode);
  } else {
    toPos = fromPos.clone();
    toPos.y += 3;
  }
  if (!fromVis && !toVis) return;

  const color = CONN_COLORS[conn.type] || 0xffffff;
  const points = [fromPos, toPos];
  if (Math.abs(fromPos.y - toPos.y) > 2) {
    const mid = fromPos.clone().lerp(toPos, 0.5);
    points.splice(1, 0, mid);
  }

  const curve = new THREE.CatmullRomCurve3(points);
  const tube = new THREE.TubeGeometry(curve, 20, 0.12, 6, false);
  const mat = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.35,
    transparent: true,
    opacity: 0.85,
  });
  const mesh = new THREE.Mesh(tube, mat);
  mesh.userData = { type: "connection", connId: conn.id, conn };
  scene.add(mesh);
  state.connLines.set(conn.id, mesh);

  [fromPos, toPos].forEach((p, i) => {
    if (conn.to || i === 0) {
      const marker = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.35, 0),
        new THREE.MeshStandardMaterial({
          color,
          emissive: color,
          emissiveIntensity: 0.5,
        })
      );
      marker.position.copy(p);
      marker.userData = { type: "connection", connId: conn.id, conn };
      scene.add(marker);
      if (!mesh.userData.markers) mesh.userData.markers = [];
      mesh.userData.markers.push(marker);
    }
  });
}

function rebuildScene() {
  state.roomMeshes.clear();
  state.poiMeshes.clear();
  state.connLines.clear();
  state.floorGroups.clear();
  while (scene.children.length > 3) scene.remove(scene.children[3]);
  buildZone();
  highlightSelection();
  highlightRoute();
}

function setViewMode(mode) {
  state.viewMode = mode;
  document.querySelectorAll("[data-view]").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === mode);
  });
  if (mode === "single" && !state.activeFloor) {
    state.activeFloor = state.zone.floors[1]?.id || state.zone.floors[0].id;
  }
  if (mode !== "single") state.activeFloor = null;
  rebuildScene();
  renderSidebar();
  fitCamera();
}

function setActiveFloor(floorId) {
  state.activeFloor = floorId;
  state.viewMode = "single";
  document.querySelectorAll("[data-view]").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === "single");
  });
  rebuildScene();
  renderSidebar();
  fitCamera();
}

function selectPoi(poiId) {
  state.selectedPoi = poiId;
  state.selectedConn = null;
  const poi = state.zone.pois.find((p) => p.id === poiId);
  if (poi) {
    els.hudTitle.textContent = poi.name;
    els.hudDetail.textContent = `${poi.loot ? poi.loot + " · " : ""}Floor: ${floorName(poi.floor)} · Click again to add to route`;
    focusOn(poi.floor, poi.room);
  }
  highlightSelection();
  renderSidebar();
}

function selectConn(connId) {
  state.selectedConn = connId;
  state.selectedPoi = null;
  const conn = state.zone.connections.find((c) => c.id === connId);
  if (conn) {
    els.hudTitle.textContent = `[${conn.id}] ${conn.label}`;
    els.hudDetail.textContent = `${conn.type.replace(/_/g, " ")}${conn.external ? " → " + conn.external : ""}${conn.oneWay ? " · one-way" : ""}`;
    if (conn.from) focusOn(conn.from.floor, conn.from.room);
  }
  highlightSelection();
  renderSidebar();
}

function floorName(id) {
  return state.zone.floors.find((f) => f.id === id)?.name || id;
}

function focusOn(floorId, roomId) {
  const room = getRoom(floorId, roomId);
  if (!room) return;
  const fi = state.zone.floors.findIndex((f) => f.id === floorId);
  const target = new THREE.Vector3(
    room.x + room.w / 2,
    floorY(fi, state.viewMode) + 4,
    room.z + room.d / 2
  );
  controls.target.lerp(target, 0.35);
}

function toggleRoutePoi(poiId) {
  const idx = state.route.indexOf(poiId);
  if (idx >= 0) state.route.splice(idx, 1);
  else state.route.push(poiId);
  highlightRoute();
  renderRoute();
  renderSidebar();
}

function clearRoute() {
  state.route = [];
  highlightRoute();
  renderRoute();
  renderSidebar();
}

function loadPreset(id) {
  const preset = state.zone.routes.find((r) => r.id === id);
  if (!preset) return;
  state.route = [...preset.stops];
  highlightRoute();
  renderRoute();
  renderSidebar();
  els.hudTitle.textContent = preset.name;
  els.hudDetail.textContent = preset.note || "";
}

function highlightSelection() {
  state.poiMeshes.forEach((mesh, id) => {
    const sel = id === state.selectedPoi;
    mesh.scale.setScalar(sel ? 1.35 : 1);
    if (mesh.userData.ring) mesh.userData.ring.material.opacity = sel ? 0.9 : 0.4;
  });

  state.connLines.forEach((mesh, id) => {
    const sel = id === state.selectedConn;
    mesh.material.opacity = sel ? 1 : 0.45;
    mesh.material.emissiveIntensity = sel ? 0.7 : 0.25;
    (mesh.userData.markers || []).forEach((m) => {
      m.scale.setScalar(sel ? 1.4 : 1);
    });
  });

  state.roomMeshes.forEach((mesh) => {
    mesh.material.emissiveIntensity = 0.08;
    mesh.material.opacity = 1;
  });

  if (state.selectedPoi) {
    const poi = state.zone.pois.find((p) => p.id === state.selectedPoi);
    if (poi) {
      const rm = state.roomMeshes.get(`${poi.floor}:${poi.room}`);
      if (rm) rm.material.emissiveIntensity = 0.25;
    }
  }

  if (state.selectedConn) {
    const conn = state.zone.connections.find((c) => c.id === state.selectedConn);
    if (conn?.from) {
      const rm = state.roomMeshes.get(`${conn.from.floor}:${conn.from.room}`);
      if (rm) rm.material.emissiveIntensity = 0.22;
    }
    if (conn?.to) {
      const rm = state.roomMeshes.get(`${conn.to.floor}:${conn.to.room}`);
      if (rm) rm.material.emissiveIntensity = 0.22;
    }
  }
}

function highlightRoute() {
  state.poiMeshes.forEach((mesh, id) => {
    const inRoute = state.route.includes(id);
    if (inRoute && mesh.userData.ring) {
      mesh.userData.ring.material.opacity = 0.95;
      mesh.scale.setScalar(1.2);
    } else if (id !== state.selectedPoi) {
      mesh.scale.setScalar(1);
    }
  });
  drawRouteLine();
}

function drawRouteLine() {
  if (state.routeLine) {
    scene.remove(state.routeLine);
    state.routeLine = null;
  }
  if (state.route.length < 2) return;

  const points = [];
  state.route.forEach((poiId) => {
    const poi = state.zone.pois.find((p) => p.id === poiId);
    if (!poi) return;
    const room = getRoom(poi.floor, poi.room);
    if (!room) return;
    const fi = state.zone.floors.findIndex((f) => f.id === poi.floor);
    const p = roomCenter(room);
    p.y = floorY(fi, state.viewMode) + 1.5;
    points.push(p);
  });

  if (points.length < 2) return;
  const curve = new THREE.CatmullRomCurve3(points);
  const geo = new THREE.TubeGeometry(curve, 64, 0.2, 8, false);
  const mat = new THREE.MeshBasicMaterial({ color: 0xffee88, transparent: true, opacity: 0.75 });
  state.routeLine = new THREE.Mesh(geo, mat);
  scene.add(state.routeLine);
}

function renderSidebar() {
  els.floorList.innerHTML = state.zone.floors.map((f) =>
    `<button class="mp-floor-btn ${state.activeFloor === f.id ? "active" : ""}" data-floor="${f.id}">` +
    `<span class="mp-floor-swatch" style="background:${f.color}"></span>` +
    `<span><strong>${f.label || f.name}</strong><br><span style="color:var(--muted);font-size:.72rem">${f.name}</span></span>` +
    `</button>`
  ).join("");

  els.floorList.querySelectorAll("[data-floor]").forEach((btn) => {
    btn.addEventListener("click", () => setActiveFloor(btn.dataset.floor));
  });

  els.poiList.innerHTML = state.zone.pois.map((p) =>
    `<div class="mp-poi ${state.selectedPoi === p.id ? "active" : ""} ${state.route.includes(p.id) ? "in-route" : ""}" data-poi="${p.id}">` +
    `<span class="mp-poi-num">${p.num}</span>` +
    `<span class="mp-poi-name">${p.name}</span>` +
    (p.loot ? `<span class="mp-poi-tag ${p.loot}">${p.loot}</span>` : "") +
    `</div>`
  ).join("");

  els.poiList.querySelectorAll("[data-poi]").forEach((el) => {
    el.addEventListener("click", () => selectPoi(el.dataset.poi));
    el.addEventListener("dblclick", () => toggleRoutePoi(el.dataset.poi));
  });

  els.connList.innerHTML = state.zone.connections.map((c) =>
    `<div class="mp-conn ${state.selectedConn === c.id ? "active" : ""}" data-conn="${c.id}">` +
    `<span class="mp-conn-id">${c.id}</span>${c.label}` +
    `<div class="mp-conn-type">${c.type.replace(/_/g, " ")}</div></div>`
  ).join("");

  els.connList.querySelectorAll("[data-conn]").forEach((el) => {
    el.addEventListener("click", () => selectConn(el.dataset.conn));
  });

  renderRoute();
}

function renderRoute() {
  if (!state.route.length) {
    els.routeList.innerHTML = `<p style="color:var(--muted);margin:0;font-size:.78rem">Double-click POIs in the list or 3D view to build a farming loop.</p>`;
    return;
  }
  els.routeList.innerHTML = state.route.map((id, i) => {
    const p = state.zone.pois.find((x) => x.id === id);
    return `<div class="mp-route-stop"><span class="mp-route-num">${i + 1}</span><span>${p?.name || id}</span></div>`;
  }).join("");
}

function onPointerMove(ev) {
  const rect = els.viewport.getBoundingClientRect();
  mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(scene.children, true);
  const hit = hits.find((h) => h.object.userData?.type);
  if (hit) {
    const ud = hit.object.userData;
    let text = "";
    if (ud.type === "poi") text = `<strong>${ud.poi.name}</strong>${ud.poi.loot ? " · " + ud.poi.loot : ""}`;
    else if (ud.type === "room") text = `<strong>${ud.name}</strong>`;
    else if (ud.type === "connection") text = `<strong>[${ud.conn.id}]</strong> ${ud.conn.label}`;
    if (text) {
      els.tooltip.innerHTML = text;
      els.tooltip.style.display = "block";
      els.tooltip.style.left = `${ev.clientX - rect.left + 12}px`;
      els.tooltip.style.top = `${ev.clientY - rect.top + 12}px`;
      els.viewport.style.cursor = "pointer";
      return;
    }
  }
  els.tooltip.style.display = "none";
  els.viewport.style.cursor = "grab";
}

function onClick(ev) {
  const rect = els.viewport.getBoundingClientRect();
  mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(scene.children, true);
  const hit = hits.find((h) => h.object.userData?.type);
  if (!hit) return;
  const ud = hit.object.userData;
  if (ud.type === "poi") {
    if (ev.detail === 2) toggleRoutePoi(ud.poiId);
    else selectPoi(ud.poiId);
  } else if (ud.type === "connection") selectConn(ud.connId);
  else if (ud.type === "room") {
    els.hudTitle.textContent = ud.name;
    els.hudDetail.textContent = `Floor: ${floorName(ud.floorId)}`;
    focusOn(ud.floorId, ud.roomId);
  }
}

function fitCamera() {
  const box = new THREE.Box3();
  scene.traverse((obj) => {
    if (obj.isMesh && obj.userData?.type) box.expandByObject(obj);
  });
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const dist = Math.max(size.x, size.y, size.z) * 1.1;
  camera.position.set(center.x + dist * 0.7, center.y + dist * 0.55, center.z + dist * 0.7);
  controls.target.copy(center);
  controls.update();
}

function onResize() {
  const wrap = els.viewport.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

function animate() {
  animId = requestAnimationFrame(animate);
  controls.update();

  const t = performance.now() * 0.001;
  state.poiMeshes.forEach((mesh, id) => {
    if (state.route.includes(id) || id === state.selectedPoi) {
      mesh.position.y += Math.sin(t * 3 + id.length) * 0.002;
    }
  });

  renderer.render(scene, camera);
}

init().catch((err) => {
  console.error(err);
  document.body.innerHTML = `<p style="padding:2rem;color:#c45c4a">Failed to load map viewer: ${err.message}. Serve via a local HTTP server (file:// blocks ES modules).</p>`;
});
