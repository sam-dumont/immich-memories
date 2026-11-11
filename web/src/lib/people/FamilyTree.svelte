<script lang="ts">
  import { Button, Heading, LoadingSpinner, Text } from '@immich/ui';
  import { mdiCheck, mdiFileImageOutline, mdiFileOutline } from '@mdi/js';
  import { api } from '#lib/api.ts';
  import { t, tn } from '#lib/i18n.svelte.ts';
  import { sendPerson } from './rosterApi';
  import { draw, FACE, type Dotted, type FamilyTree } from './treeDrawing';
  import { saveFile, treePng, treeSvg } from './treeExport';
  import type { Roster } from './types';

  let { roster, refresh = 0, onOpen, onChanged }: { roster: Roster; refresh?: number; onOpen: (personId: string) => void; onChanged: () => void } = $props();

  let open = $state(false);
  let tree = $state<FamilyTree | null>(null);
  let failed = $state(false);
  let svg = $state<SVGSVGElement>();

  let loadVersion = 0;
  $effect(() => {
    refresh;
    if (!open) return;
    const version = ++loadVersion;
    api<FamilyTree>('/roster/tree')
      .then((loaded) => {
        if (version === loadVersion) [tree, failed] = [loaded, false];
      })
      .catch(() => {
        if (version === loadVersion) failed = true;
      });
  });

  const drawing = $derived(tree ? draw(tree) : null);
  const label = (kind: string) => roster.relationships.find((c) => c.kind === kind)?.label ?? kind.replaceAll('-', ' ');
  // The chain the suggestion follows, as the person's card words it.
  const why = (line: Dotted) =>
    roster.people.find((p) => p.person_id === line.source.person_id)?.links.find((l) => l.status === 'suggested' && l.kind === line.kind && l.target_id === line.target.person_id)?.via ?? '';
  const short = (name: string) => (name.length > 16 ? `${name.slice(0, 15)}…` : name);

  async function confirm(line: Dotted) {
    const saved = await sendPerson('POST', `/${encodeURIComponent(line.source.person_id)}/relationships`, { kind: line.kind, target_id: line.target.person_id });
    if (saved) onChanged();
  }

  const onKey = (event: KeyboardEvent, act: () => void) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      act();
    }
  };

  async function save(format: 'svg' | 'png') {
    if (!svg) return;
    const file = format === 'svg' ? new Blob([await treeSvg(svg)], { type: 'image/svg+xml' }) : await treePng(svg);
    saveFile(`family-tree.${format}`, file);
  }
</script>

<section class="flex min-w-0 flex-col gap-2 rounded-2xl border border-gray-200 p-4 dark:border-gray-800" aria-label={t('Family tree')}>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <Heading size="tiny" tag="h2">{t('Family tree')}</Heading>
    <Button size="small" variant="outline" onclick={() => (open = !open)} aria-expanded={open}>{open ? t('Hide the family tree') : t('Draw the family tree')}</Button>
  </div>
  {#if open}
    {#if failed}
      <p class="text-sm text-danger" role="alert">{t('Could not draw the family tree.')}</p>
    {:else if !tree || !drawing}
      <LoadingSpinner />
    {:else if !tree.people.length}
      <Text size="small" color="muted">{t('No family links confirmed yet. Give someone a parent, a partner or a sibling below and the tree draws itself.')}</Text>
    {:else}
      <Text size="small" color="muted">{t('Drawn from the relationships you confirmed. A dotted line is a suggestion: its tick confirms it. Click someone to open their card.')}</Text>
      {#if tree.left_out}<Text size="small" color="muted"><span data-testid="tree-left-out">{tn('{n} person with no family link is left out.', '{n} people with no family link are left out.', tree.left_out)}</span></Text>{/if}
      <div class="max-w-full overflow-x-auto">
        <svg bind:this={svg} width={drawing.width} height={drawing.height} viewBox={`0 0 ${drawing.width} ${drawing.height}`} class="mx-auto block text-gray-900 dark:text-gray-100" role="group" aria-label={t('Family tree')} font-family="Inter, ui-sans-serif, system-ui, sans-serif">
          <defs><clipPath id="tree-face" clipPathUnits="objectBoundingBox"><circle cx="0.5" cy="0.5" r="0.5" /></clipPath></defs>
          <g data-export="skip">
            {#each drawing.dotted as line (`${line.source.person_id}:${line.target.person_id}`)}
              <path d={line.d} fill="none" class="stroke-primary" stroke-width="2" stroke-dasharray="2 5" stroke-linecap="round" data-testid="tree-suggestion" />
            {/each}
          </g>
          {#each drawing.lines as line, index (index)}
            <path d={line.d} fill="none" class="stroke-gray-400 dark:stroke-gray-500" stroke-width="2" stroke-dasharray={line.dashed ? '6 5' : undefined} data-testid={line.testid} data-dashed={line.dashed} />
          {/each}
          {#each drawing.knots as knot, index (index)}
            <circle cx={knot.x} cy={knot.y} r="5" class={knot.dashed ? 'fill-light stroke-gray-400 dark:stroke-gray-500' : 'fill-gray-400 dark:fill-gray-500'} stroke-width="2" stroke-dasharray={knot.dashed ? '3 3' : undefined} data-testid="tree-knot" data-dashed={knot.dashed} />
          {/each}
          {#each drawing.nodes as node (node.person_id)}
            <g role="button" tabindex="0" aria-label={node.name} class="cursor-pointer outline-none focus-visible:opacity-70" data-testid="tree-person" data-person-id={node.person_id} data-owner={node.owner}
              onclick={() => onOpen(node.person_id)} onkeydown={(event) => onKey(event, () => onOpen(node.person_id))}>
              <title>{node.name}</title>
              <circle cx={node.cx} cy={node.cy} r={FACE} class="fill-gray-200 dark:fill-gray-700" />
              <text x={node.cx} y={node.cy + 5} text-anchor="middle" font-size="15" font-weight="600" class="fill-gray-600 dark:fill-gray-300">{node.initials}</text>
              <image href={`/api/v1/people/${encodeURIComponent(node.person_id)}/face`} x={node.cx - FACE} y={node.cy - FACE} width={FACE * 2} height={FACE * 2} clip-path="url(#tree-face)" preserveAspectRatio="xMidYMid slice"
                onerror={(event) => ((event.currentTarget as SVGImageElement).style.visibility = 'hidden')} />
              <circle cx={node.cx} cy={node.cy} r={FACE} fill="none" class={node.owner ? 'stroke-primary' : 'stroke-gray-300 dark:stroke-gray-600'} stroke-width={node.owner ? 4 : 1.5} />
              <text x={node.cx} y={node.cy + FACE + 20} text-anchor="middle" font-size="13" font-weight={node.owner ? 700 : 500} fill="currentColor">{short(node.name)}</text>
              {#if node.birth_year}
                <text x={node.cx} y={node.cy + FACE + 37} text-anchor="middle" font-size="12" class="fill-gray-500 dark:fill-gray-400">{node.birth_year}</text>
              {:else}
                <text x={node.cx} y={node.cy + FACE + 37} text-anchor="middle" font-size="11" font-style="italic" class="fill-warning" data-testid="tree-no-birth-year">{t('birth year?')}</text>
              {/if}
            </g>
          {/each}
          <g data-export="skip">
            {#each drawing.dotted as line (`${line.source.person_id}:${line.target.person_id}`)}
              {@const question = t('Confirm that {name} is {relationship} {other}', { name: line.source.name, relationship: label(line.kind), other: line.target.name })}
              <g role="button" tabindex="0" aria-label={question} class="cursor-pointer" data-testid="tree-confirm" onclick={() => confirm(line)} onkeydown={(event) => onKey(event, () => confirm(line))}>
                <title>{question}{why(line) ? ` (${why(line)})` : ''}</title>
                <circle cx={line.button.x} cy={line.button.y} r="11" class="fill-light stroke-primary" stroke-width="2" />
                <path d={mdiCheck} transform={`translate(${line.button.x - 8} ${line.button.y - 8}) scale(0.6667)`} class="fill-primary" />
              </g>
            {/each}
          </g>
        </svg>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button size="small" variant="outline" leadingIcon={mdiFileOutline} onclick={() => save('svg')}>{t('Save as SVG')}</Button>
        <Button size="small" variant="outline" leadingIcon={mdiFileImageOutline} onclick={() => save('png')}>{t('Save as PNG')}</Button>
      </div>
      <Text size="small" color="muted">{t('The files are made in this browser. Nothing is uploaded.')}</Text>
    {/if}
  {/if}
</section>
