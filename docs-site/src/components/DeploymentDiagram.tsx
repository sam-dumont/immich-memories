import React, {useEffect, useId, useRef, useState} from 'react';
import styles from './DeploymentDiagram.module.css';
import {model, phases, titles, type Node, type Topology, type Phase} from './deploymentModel.ts';

function Icon({kind}: {kind: Node['kind'] | 'disk'}) {
  const paths = {
    server: 'M4 3h16v7H4z M4 14h16v7H4z M7 6h1 M7 17h1 M12 6h5 M12 17h5',
    chip: 'M7 7h10v10H7z M10 10h4v4h-4z M9 3v4 M15 3v4 M9 17v4 M15 17v4 M3 9h4 M3 15h4 M17 9h4 M17 15h4',
    photos: 'M3 5h18v15H3z M3 16l5-5 5 5 3-3 5 5 M15 9h.01',
    browser: 'M3 4h18v16H3z M3 9h18 M6 6.5h.01 M9 6.5h.01',
    disk: 'M4 5c0-4 16-4 16 0s-16 4-16 0v14c0 4 16 4 16 0V5 M4 12c0 4 16 4 16 0',
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[kind]} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export default function DeploymentDiagram({topology = 'basic', chooseTopology = false}: {topology?: Topology; chooseTopology?: boolean}) {
  const [view, setView] = useState(topology);
  const [phase, setPhase] = useState<Phase>('prepare');
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<{key: string; width: number; height: number; paths: {path: string; bypass?: boolean; badge: [number, number]}[]}>({key: '', width: 1, height: 1, paths: []});
  const canvas = useRef<HTMLDivElement>(null);
  const marker = `arrow-${useId().replace(/:/g, '')}`;
  const {groups, flows, note} = model(view, phase);
  const selectedNode = groups.flatMap(group => group.nodes).find(node => node.name === selected);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const measure = () => {
      const bounds = element.getBoundingClientRect();
      const boxes = new Map(Array.from(element.querySelectorAll<HTMLElement>('[data-machine]')).map(item => [item.dataset.machine!, item.getBoundingClientRect()]));
      const paths = flows.map(flow => {
        const a = boxes.get(flow.from)!, b = boxes.get(flow.to)!;
        const vertical = Math.abs(a.left - b.left) < 10;
        if (vertical) {
          if (flow.bypass) {
            const x = a.left - bounds.left + 1, end = b.left - bounds.left + 1;
            return `M ${x} ${a.top - bounds.top + 30} H 8 V ${b.top - bounds.top + 30} H ${end}`;
          }
          const down = a.top < b.top;
          const x = a.left - bounds.left + a.width / 2;
          const y = (down ? a.bottom : a.top) - bounds.top;
          const end = (down ? b.top : b.bottom) - bounds.top;
          return `M ${x} ${y} L ${x} ${end}`;
        }
        if (flow.bypass) {
          const x = a.left - bounds.left + a.width / 2, end = b.left - bounds.left + b.width / 2;
          const y = a.bottom - bounds.top, finish = b.bottom - bounds.top;
          const bottom = bounds.height - 9;
          return `M ${x} ${y} V ${bottom - 8} Q ${x} ${bottom} ${x - 8} ${bottom} H ${end + 8} Q ${end} ${bottom} ${end} ${bottom - 8} V ${finish}`;
        }
        const right = a.left < b.left;
        const x = (right ? a.right : a.left) - bounds.left, end = (right ? b.left : b.right) - bounds.left;
        const y = a.top - bounds.top + 74, finish = b.top - bounds.top + 74;
        const mid = (x + end) / 2;
        return `M ${x} ${y} C ${mid} ${y}, ${mid} ${finish}, ${end} ${finish}`;
      });
      setDrawing({key: `${view}:${phase}`, width: bounds.width, height: bounds.height,
        paths: paths.map((path, index) => {
          const flow = flows[index], a = boxes.get(flow.from)!, b = boxes.get(flow.to)!;
          const vertical = Math.abs(a.left - b.left) < 10;
          const badge: [number, number] = flow.bypass
            ? vertical ? [8, (a.top + b.top) / 2 - bounds.top + 30] : [(a.left + a.width / 2 + b.left + b.width / 2) / 2 - bounds.left, bounds.height - 9]
            : vertical ? [a.left + a.width / 2 - bounds.left, (a.top < b.top ? a.bottom + b.top : b.bottom + a.top) / 2 - bounds.top]
            : [(a.left < b.left ? a.right + b.left : b.right + a.left) / 2 - bounds.left, a.top - bounds.top + 74];
          return {path, bypass: flow.bypass, badge};
        })});
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    element.querySelectorAll('[data-machine]').forEach(item => observer.observe(item));
    measure();
    return () => observer.disconnect();
  }, [view, phase]);
  return <figure className={styles.figure} aria-label={`${titles[view]}: ${phases.find(item => item.id === phase)!.label}`}>
    <div className={styles.header}>
      <div><span className={styles.eyebrow}>Deployment explorer</span><strong>{titles[view]}</strong></div>
      {chooseTopology && <label className={styles.selectLabel}>Setup<select aria-label="Deployment setup" value={view} onChange={event => {setView(event.target.value as Topology); setSelected(null);}}>{Object.entries(titles).map(([key, title]) => <option value={key} key={key}>{title}</option>)}</select></label>}
    </div>
    <div className={styles.controls} role="group" aria-label="Processing phase">{phases.map(item => <button key={item.id} type="button" aria-pressed={phase === item.id} onClick={() => {setPhase(item.id); setSelected(null);}}>{item.label}</button>)}</div>
    <div ref={canvas} className={styles.canvas}>
      <svg className={styles.wires} viewBox={`0 0 ${drawing.width} ${drawing.height}`} aria-hidden="true"><defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>{drawing.key === `${view}:${phase}` && drawing.paths.map(({path, bypass, badge}, index) => <g key={index}><path d={path} markerEnd={`url(#${marker})`} className={bypass ? styles.bypass : undefined} /><circle cx={badge[0]} cy={badge[1]} r="8" /><text x={badge[0]} y={badge[1]} dy=".35em">{index + 1}</text></g>)}</svg>
      {groups.map(group => <section key={group.id} className={styles.machine} data-machine={group.id} aria-label={group.title}>
        <div className={styles.machineHeading}><span>{group.boundary}</span><h3>{group.title}</h3></div>
        <div className={styles.nodes}>{group.nodes.map(node => <button type="button" className={styles.node} key={node.name} aria-pressed={selected === node.name} onClick={() => setSelected(selected === node.name ? null : node.name)}><Icon kind={node.kind} /><span><strong>{node.name}</strong><small>{node.sub}</small></span></button>)}</div>
        {group.storage && <div className={styles.storage}><Icon kind="disk" /><span>{group.storage}</span></div>}
      </section>)}
    </div>
    <div className={styles.flows}>{flows.map((flow, index) => <div key={flow.label}><span className={styles.number}>{index + 1}</span><p><strong>{flow.label}</strong><span>{flow.detail}</span></p></div>)}</div>
    <div className={styles.detail} aria-live="polite">{selectedNode ? <><strong>{selectedNode.name}</strong><p>{selectedNode.detail}</p></> : <p>{note} <span className={styles.hint}>Select a service for details.</span></p>}</div>
  </figure>;
}
