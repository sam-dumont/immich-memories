# Visual Style Guide

Shared design tokens between the NiceGUI web app and the Docusaurus docs site.
Both must look like they're part of the same product.

## Colors

### Primary
| Token | Light | Dark |
|-------|-------|------|
| Primary | `#4250af` | `#6B8FE8` |
| Primary hover | `#3a47a0` | `#5A7FD8` |
| Primary tint (backgrounds) | `rgba(66, 80, 175, 0.08)` | `rgba(107, 143, 232, 0.12)` |

### Backgrounds
| Token | Light | Dark |
|-------|-------|------|
| Main background | `#ffffff` | `#000000` |
| Surface / elevated | `#f6f6f4` | `#222222` |

### Text
| Token | Light | Dark |
|-------|-------|------|
| Primary text | `#000000` | `#dbdbdb` |
| Secondary text | `#6b7280` | `#d4d4d4` |
| Muted text | `#9ca3af` | `#a1a1a1` |

### Borders
| Token | Light | Dark |
|-------|-------|------|
| Border | `#e5e7eb` | `#262626` |
| Border light | `#f3f4f6` | `#262626` |

### Status
| Token | Light | Dark |
|-------|-------|------|
| Success | `#2e7d32` | `#81c784` |
| Warning | `#b45309` | `#f57c00` |
| Error | `#c62828` | `#e57373` |
| Info | `#4250af` | `#6B8FE8` |

## Typography

**Font:** Inter, bundled and self-hosted; nothing is fetched from Google Fonts
**Fallbacks:** `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
**No serif fonts. Ever.**

| Weight | Usage |
|--------|-------|
| 400 | Body text |
| 500 | Emphasis, labels |
| 600 | Section headers, sidebar active |
| 700 | Page titles, brand |

Font smoothing: `-webkit-font-smoothing: antialiased`

## Spacing & Shape

| Token | Value |
|-------|-------|
| Border radius (cards, inputs) | `10px` |
| Border radius (badges) | `6px` |
| Border radius (circular) | `50%` |

## Shadows

| Token | Light | Dark |
|-------|-------|------|
| Shadow | `0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)` | `none` |
| Shadow MD | `0 4px 6px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.04)` | `0 2px 8px rgba(0,0,0,0.4)` |

## Transitions

All interactive elements: `transition: all 0.15s ease`

## Dark mode

- True black background (`#000000`), not dark gray
- Surface elements use `#222222`
- Borders use `#262626`
- System preference respected by default

## What to avoid

- Serif fonts
- Warm amber/orange color schemes (that's not us)
- Heavy shadows or glassmorphism
- Emoji as icons in feature cards
- Generic value props ("GPU fast!", "enterprise-ready")

## Where tokens are defined

- **NiceGUI app:** `src/immich_memories/ui/theme.py`
- **Docusaurus:** `docs-site/src/css/custom.css`

## Documentation presentation

- Discovery and task pages explain the next action. Link exact thresholds, service contracts and implementation details into advanced reference pages.
- One diagram answers one question. Use short labels, a vertical flow on narrow pages, and split a graph when unrelated branches compete for space. Architecture diagrams name services and show real data or control flow.
- Mermaid labels stay at 16 px. The wrapper preserves native SVG size and offers keyboard scrolling only when a graph is wider than the article. Do not shrink it to fit.
- Use the blue app palette in light and dark mode. Diagrams inherit Inter and the docs theme. Add `accTitle` and `accDescr` when a diagram needs an accessible description.
- Every code fence names its language. Commands use `bash`; command output and logs use `text`. YAML, SQL, HCL and diffs get their own syntax highlighting. Keep outputs out of copyable command blocks.
- Homepage examples use the shared Docusaurus `CodeBlock`, including its copy button. No imitation terminal chrome.
- Public product copy uses “Turn your Immich photos and videos into memory films.” The output is a film; the selection before rendering is a cut. Page descriptions describe the page's task.
