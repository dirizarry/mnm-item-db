import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";

const els = {};
const state = {
  data: null,
  layout: {},
  roomGroups: new Map(),
  selected: null,
  snap: 0.5,
  refVisible: true,
  transformMode: "translate",
  dragY: false,
};

let scene, camera, renderer, orbit, transform, raycaster, mouse;
let refPlane = null;

async function init() {
  cacheEls();
  const res = await fetch("data/wyrmsbane-rooms-3d.json");
  state.data = await res.json();
  document.getElementById("zone-title").textContent = `${state.data.name} — 3D layout editor`;

  loadLayout() || scatterLayout();
  bindUi();
  setupThree();
  buildRooms();
  buildRefPlane();
  renderRoomList();
  updatePosFields();
  animate();
  fitCamera();
}

function cacheEls() {
  els.viewport = document.getElementById("viewport");
  els.roomList = document.getElementById("room-list");
  els.hudTitle = document.getElementById("hud-title");
  els.hudDetail = document.getElementById("hud-detail");
  els.posFields = document.getElementById("pos-fields");
}

function bindUi() {
  document.getElementById("btn-fit").addEventListener("click", fitCamera);
  document.getElementById("btn-scatter").addEventListener("click", () => {
    if (!confirm("Scatter all rooms into open space?")) return;
    scatterLayout();
    applyAllTransforms();
    renderRoomList();
    saveLayout();
  });
  document.getElementById("btn-save").addEventListener("click", () => {
    saveLayout();
    flash("Saved locally");
  });
  document.getElementById("btn-export").addEventListener("click", exportLayout);
  document.getElementById("btn-reset").addEventListener("click", () => {
    if (!confirm("Clear saved layout?")) return;
    localStorage.removeItem(state.data.storageKey);
    scatterLayout();
    applyAllTransforms();
    renderRoomList();
  });

  document.getElementById("ref-toggle").addEventListener("change", (e) => {
    state.refVisible = e.target.checked;
    if (refPlane) refPlane.visible = state.refVisible;
  });

  document.getElementById("snap-toggle").addEventListener("change", (e) => {
    state.snap = e.target.checked ? 0.5 : 0;
    if (transform) transform.setTranslationSnap(state.snap || null);
  });

  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => setTransformMode(btn.dataset.mode));
  });

  ["px", "py", "pz", "ry"].forEach((id) => {
    document.getElementById(id).addEventListener("change", applyPosFields);
  });

  els.viewport.addEventListener("click", onClick);
  window.addEventListener("resize", onResize);
  window.addEventListener("keydown", onKey);
}

function setupThree() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0908);
  scene.fog = new THREE.FogExp2(0x0a0908, 0.008);

  const wrap = els.viewport.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;

  camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 400);
  camera.position.set(30, 28, 36);

  renderer = new THREE.WebGLRenderer({ canvas: els.viewport, antialias: true });
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;

  orbit = new OrbitControls(camera, els.viewport);
  orbit.enableDamping = true;
  orbit.dampingFactor = 0.06;
  orbit.maxPolarAngle = Math.PI * 0.49;

  transform = new TransformControls(camera, els.viewport);
  transform.setMode("translate");
  transform.setTranslationSnap(state.snap);
  transform.addEventListener("dragging-changed", (ev) => {
    orbit.enabled = !ev.value;
  });
  transform.addEventListener("change", () => {
    if (!state.selected) return;
    syncLayoutFromGroup(state.selected);
    updatePosFields();
    renderRoomList();
  });
  scene.add(transform);

  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  scene.add(new THREE.AmbientLight(0x6a6050, 0.6));
  const sun = new THREE.DirectionalLight(0xffeed8, 0.95);
  sun.position.set(25, 50, 20);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x5eb8c9, 0.3);
  fill.position.set(-15, 25, -10);
  scene.add(fill);

  const grid = new THREE.GridHelper(80, 80, 0x3d3426, 0x1f1a13);
  scene.add(grid);
}

function partMaterial(part, baseColor, roomId) {
  const c = new THREE.Color(baseColor);
  if (part.t === "pool") {
    return new THREE.MeshStandardMaterial({
      color: 0x3a8acc,
      emissive: 0x2a6aaa,
      emissiveIntensity: 0.6,
      roughness: 0.3,
      metalness: 0.2,
      transparent: true,
      opacity: 0.85,
    });
  }
  if (part.t === "stairs") {
    return new THREE.MeshStandardMaterial({ color: 0x6a5a4a, roughness: 0.85 });
  }
  if (part.t === "pillar") {
    return new THREE.MeshStandardMaterial({ color: 0x5a5a5a, roughness: 0.7 });
  }
  if (part.t === "wall" || part.t === "arch") {
    const m = c.clone().multiplyScalar(0.55);
    return new THREE.MeshStandardMaterial({ color: m, roughness: 0.9 });
  }
  if (part.t === "altar") {
    return new THREE.MeshStandardMaterial({ color: 0x4a4035, roughness: 0.8 });
  }
  const slab = c.clone();
  return new THREE.MeshStandardMaterial({
    color: slab,
    roughness: 0.75,
    emissive: slab,
    emissiveIntensity: 0.06,
  });
}

function buildRoomGroup(room) {
  const group = new THREE.Group();
  group.userData = { roomId: room.id, room };

  const color = room.color || "#6a6a6a";
  room.parts.forEach((part) => {
    const geo = new THREE.BoxGeometry(part.w, part.h, part.d);
    const mesh = new THREE.Mesh(geo, partMaterial(part, color, room.id));
    mesh.position.set(
      part.x + part.w / 2,
      part.y + part.h / 2,
      part.z + part.d / 2
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.partType = part.t;
    group.add(mesh);

    if (part.t !== "pool") {
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0x463a26, transparent: true, opacity: 0.35 })
      );
      edges.position.copy(mesh.position);
      group.add(edges);
    }
  });

  const bbox = new THREE.Box3().setFromObject(group);
  const labelY = bbox.max.y + 0.6;
  const center = bbox.getCenter(new THREE.Vector3());
  const sprite = makeLabel(room.name, center.x - group.position.x, labelY, center.z - group.position.z);
  group.add(sprite);

  return group;
}

function makeLabel(text, x, y, z) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = 512;
  canvas.height = 64;
  ctx.fillStyle = "rgba(20,17,13,0.75)";
  ctx.fillRect(0, 0, 512, 64);
  ctx.font = "24px system-ui,sans-serif";
  ctx.fillStyle = "#d9b46a";
  ctx.textAlign = "center";
  ctx.fillText(text, 256, 40);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(mat);
  sprite.position.set(x, y, z);
  sprite.scale.set(6, 0.75, 1);
  sprite.renderOrder = 999;
  return sprite;
}

function buildRooms() {
  state.data.rooms.forEach((room) => {
    const group = buildRoomGroup(room);
    const lay = state.layout[room.id] || { x: 0, y: 0, z: 0, ry: 0 };
    group.position.set(lay.x, lay.y, lay.z);
    group.rotation.y = THREE.MathUtils.degToRad(lay.ry || 0);
    scene.add(group);
    state.roomGroups.set(room.id, group);
  });
}

function buildRefPlane() {
  const { width, depth, y } = state.data.refPlane;
  const loader = new THREE.TextureLoader();
  loader.load(state.data.refImage, (tex) => {
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    });
    refPlane = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), mat);
    refPlane.rotation.x = -Math.PI / 2;
    refPlane.position.set(width / 2 - 8, y, depth / 2 - 6);
    refPlane.visible = state.refVisible;
    scene.add(refPlane);
  });
}

function scatterLayout() {
  const { spread, yRange } = state.data.scatter;
  state.layout = {};
  state.data.rooms.forEach((room, i) => {
    const angle = (i / state.data.rooms.length) * Math.PI * 2;
    const r = spread * 0.45 + Math.random() * spread * 0.25;
    state.layout[room.id] = {
      x: Math.cos(angle) * r,
      y: yRange[0] + Math.random() * (yRange[1] - yRange[0]),
      z: Math.sin(angle) * r,
      ry: Math.round(Math.random() * 3) * 90,
    };
  });
}

function loadLayout() {
  try {
    const raw = localStorage.getItem(state.data.storageKey);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved.layout) return false;
    state.layout = saved.layout;
    return true;
  } catch {
    return false;
  }
}

function saveLayout() {
  localStorage.setItem(state.data.storageKey, JSON.stringify({
    version: 1,
    zone: state.data.id,
    savedAt: new Date().toISOString(),
    layout: state.layout,
  }));
}

function exportLayout() {
  const blob = new Blob([JSON.stringify({
    version: 1,
    zone: state.data.id,
    name: state.data.name,
    layout: state.layout,
    rooms: state.data.rooms.map((r) => ({
      id: r.id,
      name: r.name,
      poi: r.poi || null,
      transform: state.layout[r.id],
    })),
  }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "wyrmsbane-3d-layout.json";
  a.click();
  URL.revokeObjectURL(a.href);
}

function syncLayoutFromGroup(id) {
  const g = state.roomGroups.get(id);
  if (!g) return;
  const snap = state.snap;
  state.layout[id] = {
    x: snap ? Math.round(g.position.x / snap) * snap : g.position.x,
    y: snap ? Math.round(g.position.y / snap) * snap : g.position.y,
    z: snap ? Math.round(g.position.z / snap) * snap : g.position.z,
    ry: Math.round(THREE.MathUtils.radToDeg(g.rotation.y)),
  };
  if (snap) {
    g.position.set(state.layout[id].x, state.layout[id].y, state.layout[id].z);
  }
}

function applyAllTransforms() {
  state.data.rooms.forEach((room) => {
    const g = state.roomGroups.get(room.id);
    const lay = state.layout[room.id];
    if (!g || !lay) return;
    g.position.set(lay.x, lay.y, lay.z);
    g.rotation.y = THREE.MathUtils.degToRad(lay.ry || 0);
  });
}

function selectRoom(id) {
  state.selected = id;
  const g = state.roomGroups.get(id);
  const room = state.data.rooms.find((r) => r.id === id);
  if (g) {
    transform.attach(g);
    highlightSelected();
  }
  if (room) {
    els.hudTitle.textContent = room.name;
    els.hudDetail.textContent = room.poi ? `POI: ${room.poi}` : "Corridor segment — drag gizmo to place";
  }
  renderRoomList();
  updatePosFields();
}

function highlightSelected() {
  state.roomGroups.forEach((g, id) => {
    g.traverse((ch) => {
      if (ch.isMesh && ch.material?.emissive) {
        const base = id === state.selected ? 0.18 : 0.06;
        ch.material.emissiveIntensity = ch.userData.partType === "pool" ? 0.6 : base;
      }
    });
  });
}

function setTransformMode(mode) {
  state.transformMode = mode;
  transform.setMode(mode);
  document.querySelectorAll("[data-mode]").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  document.getElementById("mode-label").textContent = mode;
}

function renderRoomList() {
  els.roomList.innerHTML = state.data.rooms.map((r) => {
    const lay = state.layout[r.id] || {};
    return `<div class="ed-room ${state.selected === r.id ? "active" : ""}" data-id="${r.id}">` +
      `<span class="ed-swatch" style="background:${r.color}"></span>` +
      `<span>${r.name}</span></div>`;
  }).join("");
  els.roomList.querySelectorAll(".ed-room").forEach((el) => {
    el.addEventListener("click", () => selectRoom(el.dataset.id));
  });
}

function updatePosFields() {
  if (!state.selected) return;
  const lay = state.layout[state.selected] || { x: 0, y: 0, z: 0, ry: 0 };
  document.getElementById("px").value = lay.x.toFixed(1);
  document.getElementById("py").value = lay.y.toFixed(1);
  document.getElementById("pz").value = lay.z.toFixed(1);
  document.getElementById("ry").value = lay.ry || 0;
}

function applyPosFields() {
  if (!state.selected) return;
  state.layout[state.selected] = {
    x: parseFloat(document.getElementById("px").value) || 0,
    y: parseFloat(document.getElementById("py").value) || 0,
    z: parseFloat(document.getElementById("pz").value) || 0,
    ry: parseFloat(document.getElementById("ry").value) || 0,
  };
  applyAllTransforms();
  saveLayout();
  renderRoomList();
}

function onClick(ev) {
  const rect = els.viewport.getBoundingClientRect();
  mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const meshes = [];
  state.roomGroups.forEach((g) => g.traverse((c) => { if (c.isMesh) meshes.push(c); }));
  const hits = raycaster.intersectObjects(meshes, false);
  if (!hits.length) return;
  let obj = hits[0].object;
  while (obj && !obj.userData?.roomId) obj = obj.parent;
  if (obj?.userData?.roomId) selectRoom(obj.userData.roomId);
}

function onKey(ev) {
  if (ev.key === "g" || ev.key === "G") setTransformMode("translate");
  if (ev.key === "r" || ev.key === "R") setTransformMode("rotate");
  if (ev.key === "Escape") { transform.detach(); state.selected = null; highlightSelected(); }
  if ((ev.key === "Delete" || ev.key === "Backspace") && state.selected) {
    state.layout[state.selected].y += 1;
    applyAllTransforms();
    updatePosFields();
  }
  if (ev.key === "ArrowUp" && state.selected) nudge(0, 0.5, 0);
  if (ev.key === "ArrowDown" && state.selected) nudge(0, -0.5, 0);
  if (ev.key === "ArrowLeft" && state.selected) nudge(-0.5, 0, 0);
  if (ev.key === "ArrowRight" && state.selected) nudge(0.5, 0, 0);
  if (ev.key === "PageUp" && state.selected) nudge(0, 0, -0.5);
  if (ev.key === "PageDown" && state.selected) nudge(0, 0, 0.5);
}

function nudge(dx, dy, dz) {
  const lay = state.layout[state.selected];
  lay.x += dx;
  lay.y = Math.max(0, lay.y + dy);
  lay.z += dz;
  applyAllTransforms();
  updatePosFields();
  saveLayout();
}

function fitCamera() {
  const box = new THREE.Box3();
  state.roomGroups.forEach((g) => box.expandByObject(g));
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const dist = Math.max(size.x, size.y, size.z) * 1.4;
  camera.position.set(center.x + dist * 0.65, center.y + dist * 0.5, center.z + dist * 0.65);
  orbit.target.copy(center);
  orbit.update();
}

function onResize() {
  const wrap = els.viewport.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

function flash(msg) {
  els.hudDetail.textContent = msg;
  setTimeout(() => {
    if (state.selected) {
      const room = state.data.rooms.find((r) => r.id === state.selected);
      if (room) els.hudDetail.textContent = room.poi ? `POI: ${room.poi}` : "Corridor segment";
    }
  }, 2000);
}

function animate() {
  requestAnimationFrame(animate);
  orbit.update();
  renderer.render(scene, camera);
}

init().catch((err) => {
  document.body.innerHTML = `<p style="padding:2rem;color:#c45c4a">Editor failed: ${err.message}</p>`;
});
