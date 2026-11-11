import React, { useEffect, useRef, useState } from 'react';
export default function Scene({ sources, cited, reduced, activity, running }) {
  const root = useRef(null);
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    let disposed = false, cleanup = () => {};
    if (reduced) return;
    import('three').then(THREE => {
      if (disposed || !root.current) return;
      try {
        const host = root.current;
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
        host.replaceChildren(renderer.domElement);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
        camera.position.set(0, 2.5, 13);
        camera.lookAt(0, 0, 0);
        const objects = new THREE.Group();
        scene.add(objects);
        const addNode = (position, radius, color) => {
          const mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(radius, 1),
            new THREE.MeshBasicMaterial({ color, wireframe: true }));
          mesh.position.copy(position); objects.add(mesh); return mesh;
        };
        addNode(new THREE.Vector3(0, 0, 0), .65, 0xd9f6aa);
        sources.slice(0, 24).forEach((source, index) => {
          const angle = index * 2.39996;
          const radius = 2.3 + index % 3 * .85;
          const position = new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius * .6, (index % 5 - 2) * .6);
          const included = cited.has(source.id);
          addNode(position, included ? .23 : .16, included ? 0xd9f6aa : 0x6b979b);
          if (included) {
            const geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), position]);
            objects.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x71926a, transparent: true, opacity: .5 })));
          }
        });
        let frame=0;
        const collecting=running && activity?.stage === 'spider_fetch';
        const querying=running && activity?.stage === 'memory_retrieval';
        if (collecting) {
          const spider=new THREE.Group();
          const material=new THREE.MeshBasicMaterial({color:0xd9f6aa});
          spider.add(new THREE.Mesh(new THREE.SphereGeometry(.23,12,12),material));
          const head=new THREE.Mesh(new THREE.SphereGeometry(.13,12,12),material);head.position.y=.28;spider.add(head);
          for(let side of [-1,1]) for(let leg=0;leg<4;leg++) {
            const y=(leg-1.5)*.15;
            const points=[new THREE.Vector3(side*.13,y,0),new THREE.Vector3(side*.46,y+.2,0),new THREE.Vector3(side*.7,y-.15,0)];
            spider.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0xd9f6aa})));
          }
          spider.position.set(0,1.2,1);objects.add(spider);
          const tick=time=>{spider.position.x=Math.sin(time/900)*1.5;renderer.render(scene,camera);frame=requestAnimationFrame(tick)};
          frame=requestAnimationFrame(tick);
        }
        if(querying){
          const cylinder=new THREE.Mesh(new THREE.CylinderGeometry(.5,.5,.7,20),new THREE.MeshBasicMaterial({color:0x71926a,wireframe:true}));
          cylinder.position.set(0,1.5,1);objects.add(cylinder);
        }
        const resize = () => {
          const width = host.clientWidth, height = host.clientHeight;
          renderer.setSize(width, height);
          camera.aspect = width / height; camera.updateProjectionMatrix();
          renderer.render(scene, camera);
        };
        const observer = new ResizeObserver(resize); observer.observe(host); resize();
        const move = event => {
          objects.rotation.y = (event.offsetX / host.clientWidth - .5) * .5;
          objects.rotation.x = (event.offsetY / host.clientHeight - .5) * .2;
          renderer.render(scene, camera);
        };
        renderer.domElement.addEventListener('pointermove', move);
        cleanup = () => {
          cancelAnimationFrame(frame);
          observer.disconnect();
          renderer.domElement.removeEventListener('pointermove', move);
          scene.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); });
          renderer.dispose(); host.replaceChildren();
        };
      } catch { setFallback(true); }
    }).catch(() => setFallback(true));
    return () => { disposed = true; cleanup(); };
  }, [sources, cited, reduced, activity, running]);
  return <div className="scene" aria-label={'Knowledge map of ' + sources.length + ' stored sources'}>
    <div ref={root} className="scene-canvas" aria-hidden="true" />
    {(fallback || reduced) && <div className="scene-fallback"><span className="project-node">ARES</span>{sources.slice(0, 12).map((source, i) => <span key={source.id} className={cited.has(source.id) ? 'source-dot included' : 'source-dot'} title={source.title}>S{i + 1}</span>)}</div>}
    {running && activity?.stage === 'spider_fetch' && <p className="scene-empty">Fetching {activity.payload.pmcid} from the open-access API</p>}
    {!sources.length && activity?.stage !== 'spider_fetch' && <p className="scene-empty">Your evidence map starts with a source.</p>}
  </div>;
}
