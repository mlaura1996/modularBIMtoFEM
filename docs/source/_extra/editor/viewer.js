// 3D view of the IFC model: geometry by IFC-Lite (WebAssembly), drawn with three.js.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const IFC_LITE = "https://cdn.jsdelivr.net/npm/@ifc-lite/wasm@10.1.2/pkg/ifc-lite.js";
let ifcLite = null;

async function engine() {
  if (!ifcLite) {
    const mod = await import(IFC_LITE);
    await mod.default();
    ifcLite = mod;
  }
  return new ifcLite.IfcAPI();
}

// Meshes of every element, and the elements' attributes and property sets.
export async function loadGeometry(bytes) {
  const api = await engine();
  const pre = api.buildPrePassOnce(bytes);
  const meshes = [];
  for (let s = 0; s < pre.totalJobs; s += 100) {
    const e = Math.min(s + 100, pre.totalJobs);
    const batch = api.processGeometryBatch(bytes, pre.jobs.slice(s * 3, e * 3), pre.unitScale,
      pre.rtcOffset?.[0] ?? 0, pre.rtcOffset?.[1] ?? 0, pre.rtcOffset?.[2] ?? 0, pre.needsShift,
      pre.voidKeys, pre.voidCounts, pre.voidValues, pre.styleIds, pre.styleColors);
    for (let i = 0; i < batch.length; i++) {
      const m = batch.get(i);
      meshes.push({ id: m.expressId, type: m.ifcType, positions: m.positions, indices: m.indices,
                    origin: Array.from(m.origin), color: Array.from(m.color) });
      m.free();
    }
    batch.free();
  }
  const products = JSON.parse(new TextDecoder().decode(api.exportJson(bytes, false, true, false)));
  api.clearPrePassCache();
  api.free();
  return { meshes, products };
}

export class Viewer {
  constructor(container, { onPick }) {
    this.container = container;
    this.onPick = onPick;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.05, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enableZoom = false;            // the page scrolls; zoom with the buttons
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8070, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1, 2, 1.5);
    this.scene.add(sun);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.byId = new Map();                       // expressId -> [mesh]
    this.colors = new Map();                     // expressId -> css colour, or none for the IFC colour
    this.selected = new Set();
    this.ray = new THREE.Raycaster();
    let down = null;
    this.renderer.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
    this.renderer.domElement.addEventListener("pointerup", e => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) this.pick(e);
      down = null;
    });
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    const loop = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); requestAnimationFrame(loop); };
    loop();
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  show(meshes) {
    this.group.clear();
    this.byId.clear();
    for (const m of meshes) {
      if (m.type === "IfcOpeningElement" || m.type === "IfcSpace") continue;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(m.positions, 3));
      geo.setIndex(new THREE.BufferAttribute(m.indices, 1));
      geo.computeVertexNormals();
      const [r, g, b, a] = m.color;
      const mat = new THREE.MeshLambertMaterial({ color: new THREE.Color(r, g, b), transparent: a < 1,
                                                  opacity: a, side: THREE.DoubleSide, flatShading: true });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(...m.origin);
      mesh.userData = { id: m.id, base: new THREE.Color(r, g, b), alpha: a };
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25),
                                           new THREE.LineBasicMaterial({ color: 0x3a3630, transparent: true, opacity: 0.35 }));
      mesh.add(edges);
      this.group.add(mesh);
      if (!this.byId.has(m.id)) this.byId.set(m.id, []);
      this.byId.get(m.id).push(mesh);
    }
    this.fit();
    this.paint();
  }

  fit() {
    const box = new THREE.Box3().setFromObject(this.group);
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2;
    const d = r / Math.sin((this.camera.fov * Math.PI) / 360) * 1.05;
    this.camera.position.copy(c).add(new THREE.Vector3(0.9, 0.55, 1.2).normalize().multiplyScalar(d));
    this.camera.near = d / 100; this.camera.far = d * 20;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(c);
  }

  zoom(f) {
    const t = this.controls.target, p = this.camera.position;
    p.copy(t).add(p.clone().sub(t).multiplyScalar(f));
  }

  // colours: Map(expressId -> css colour); elements not in it are drawn grey
  // when greyOthers is set, otherwise in their IFC colour
  setColors(colors, greyOthers) {
    this.colors = colors;
    this.greyOthers = greyOthers;
    this.paint();
  }

  setSelection(ids) {
    this.selected = new Set(ids);
    this.paint();
  }

  paint() {
    const grey = new THREE.Color("#d9d4cb"), sel = new THREE.Color("#f2b01e");
    for (const [id, meshes] of this.byId) {
      for (const m of meshes) {
        const c = this.selected.has(id) ? sel
          : this.colors.has(id) ? new THREE.Color(this.colors.get(id))
          : this.greyOthers ? grey : m.userData.base;
        m.material.color.copy(c);
        m.material.emissive?.setRGB(...(this.selected.has(id) ? [0.25, 0.15, 0] : [0, 0, 0]));
      }
    }
  }

  pick(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                                             -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    const hit = this.ray.intersectObjects(this.group.children, false)[0];
    this.onPick(hit ? hit.object.userData.id : null, e.shiftKey || e.ctrlKey || e.metaKey);
  }
}
