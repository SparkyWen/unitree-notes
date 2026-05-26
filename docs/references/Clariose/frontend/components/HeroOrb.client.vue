<script setup lang="ts">
/**
 * HeroOrb — a calm pulsing orb rendered with Three.js.
 *
 * The orb is a low-poly icosahedron with a soft displacement that breathes
 * in time with a 0.25 Hz sine wave, sitting on a warm linen background.
 * The mesh is wrapped by a translucent ring that suggests "listening".
 *
 * Client-only: imports `three` directly so it never runs during SSR.
 */
import * as THREE from 'three';

const root = ref<HTMLElement | null>(null);
let renderer: THREE.WebGLRenderer | null = null;
let frame = 0;
let cleanup: (() => void) | null = null;

onMounted(() => {
  if (!root.value) return;
  const el = root.value;
  const width = el.clientWidth;
  const height = el.clientHeight;

  const scene = new THREE.Scene();
  scene.background = null;

  const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 50);
  camera.position.set(0, 0, 5.4);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);

  // Orb geometry — low-poly icosahedron with a per-vertex breathing offset.
  const geom = new THREE.IcosahedronGeometry(1.35, 4);
  const base = (geom.attributes.position as THREE.BufferAttribute).clone();

  const mat = new THREE.MeshStandardMaterial({
    color: 0xb85065,           // dusty rose — Clariose primary
    roughness: 0.42,
    metalness: 0.08,
    flatShading: true,
  });
  const orb = new THREE.Mesh(geom, mat);
  scene.add(orb);

  // Two soft halo rings — petal echoes.
  const ringGeom = new THREE.TorusGeometry(2.2, 0.010, 12, 128);
  const ringMat  = new THREE.MeshBasicMaterial({ color: 0x0b0907, transparent: true, opacity: 0.16 });
  const ring = new THREE.Mesh(ringGeom, ringMat);
  ring.rotation.x = Math.PI / 2.2;
  scene.add(ring);

  const ring2Geom = new THREE.TorusGeometry(1.85, 0.006, 10, 96);
  const ring2Mat  = new THREE.MeshBasicMaterial({ color: 0xb85065, transparent: true, opacity: 0.35 });
  const ring2 = new THREE.Mesh(ring2Geom, ring2Mat);
  ring2.rotation.x = Math.PI / 2.6;
  ring2.rotation.z = Math.PI / 5;
  scene.add(ring2);

  // Lights — warm rose key + cool sage rim + soft ivory ambient.
  const key = new THREE.DirectionalLight(0xffd9d9, 1.45);
  key.position.set(2.5, 3, 4);
  scene.add(key);

  const rim = new THREE.DirectionalLight(0x9ab18c, 0.55);
  rim.position.set(-3, -2, 2);
  scene.add(rim);

  scene.add(new THREE.AmbientLight(0xfaf3e6, 0.65));

  const tmp = new THREE.Vector3();
  const start = performance.now();

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function tick() {
    const t = (performance.now() - start) / 1000;
    const breathe = reduce ? 0 : Math.sin(t * 1.2) * 0.06 + 1;

    // Per-vertex displacement using simplex-flavoured noise (cheap radial sin).
    const pos = geom.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      tmp.fromBufferAttribute(base, i);
      const n = Math.sin(tmp.x * 1.7 + t * 0.9)
              + Math.cos(tmp.y * 1.9 + t * 0.7)
              + Math.sin(tmp.z * 1.5 + t * 1.1);
      const k = 1 + (reduce ? 0 : n * 0.018);
      pos.setXYZ(i, tmp.x * k, tmp.y * k, tmp.z * k);
    }
    pos.needsUpdate = true;
    geom.computeVertexNormals();

    orb.scale.setScalar(breathe);
    orb.rotation.y += reduce ? 0 : 0.0025;
    orb.rotation.x = Math.sin(t * 0.4) * 0.06;
    ring.rotation.z = t * 0.15;
    ring2.rotation.z = -t * 0.22;

    renderer!.render(scene, camera);
    frame = requestAnimationFrame(tick);
  }
  tick();

  function resize() {
    if (!renderer || !root.value) return;
    const w = root.value.clientWidth;
    const h = root.value.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);

  cleanup = () => {
    cancelAnimationFrame(frame);
    window.removeEventListener('resize', resize);
    geom.dispose(); ringGeom.dispose(); ring2Geom.dispose();
    mat.dispose();  ringMat.dispose();  ring2Mat.dispose();
    renderer?.dispose();
    if (renderer?.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    renderer = null;
  };
});

onBeforeUnmount(() => cleanup?.());
</script>

<template>
  <div ref="root" class="absolute inset-0" aria-hidden="true" />
</template>
