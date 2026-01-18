# FramePilot Brand Reference

> Extracted from brand guidelines v1.0 (January 2026)

## Brand Essence

**Tagline:** "Smart crops. Zero effort."

**Personality:**
- **Targeted** — We find what matters in your photos
- **Intelligent** — AI that actually works, not gimmicks
- **Sharp** — Fast, precise, no-nonsense
- **Professional** — Built for working photographers, not hobbyists

**Voice:**
- Direct and confident, not boastful
- Technical but accessible
- Action-oriented — focus on outcomes, not features
- Slightly irreverent — acknowledge pain points honestly

**Do say:** "Drop a folder. Get vertical crops. Done."
**Don't say:** "Our revolutionary AI-powered solution leverages cutting-edge technology..."

---

## Color Palette (Dark Mode Only)

### Primary Colors
| Name | Hex | Usage |
|------|-----|-------|
| Electric Orange | `#FF6B35` | Primary accent, CTAs, logo, highlights |
| Dark Charcoal | `#0F1419` | Primary background |

### Secondary Colors
| Name | Hex | Usage |
|------|-----|-------|
| Orange Dim | `#E55A2B` | Hover states, secondary accents |
| Orange Glow | `rgba(255, 107, 53, 0.15)` | Glows, subtle backgrounds |
| Orange Glow Strong | `rgba(255, 107, 53, 0.3)` | Active states, emphasis |

### Neutral Colors
| Name | Hex | Usage |
|------|-----|-------|
| Background Primary | `#0A0A0B` | Page backgrounds |
| Background Secondary | `#111113` | Cards, sections |
| Background Tertiary | `#1A1A1D` | Elevated elements |
| Background Card | `#151517` | Card backgrounds |
| Border | `#2A2A2E` | Dividers, borders |
| Text Primary | `#FFFFFF` | Headings, important text |
| Text Secondary | `#A0A0A5` | Body text |
| Text Dim | `#6B6B70` | Captions, metadata |

### Semantic Colors
| Name | Hex | Usage |
|------|-----|-------|
| Success | `#22C55E` | Checkmarks, confirmations |
| Error | `#EF4444` | Error states |
| Warning | `#F59E0B` | Warnings |

---

## Typography

### Font Family
- **Primary:** DM Sans (Google Fonts)
  - Weights: Regular (400), Medium (500), Semi-Bold (600), Bold (700)
- **Monospace:** Space Mono
  - Weights: Regular (400), Bold (700)

### Type Scale
| Element | Font | Size | Weight |
|---------|------|------|--------|
| H1 (Hero) | DM Sans | 48-60px | Bold (700) |
| H2 (Section) | DM Sans | 32-40px | Bold (700) |
| H3 (Card title) | DM Sans | 20-24px | Semi-Bold (600) |
| Body | DM Sans | 16px | Regular (400) |
| Body Small | DM Sans | 14px | Regular (400) |
| Caption | DM Sans | 12-13px | Medium (500) |
| Label | DM Sans | 12px | Semi-Bold (600) |

---

## Logo

### Elements
1. **Logomark** — Viewfinder crosshair icon (frame brackets + targeting reticle)
2. **Wordmark** — "FramePilot" in DM Sans Bold

### Variations
- Full logo (icon + wordmark) — Primary use
- Logomark only — App icon, favicon, small spaces
- Wordmark only — Text-heavy contexts

### Minimum Sizes
- Full logo: 120px width
- Logomark only: 32px width
- Favicon: 16px, 32px, 48px versions

### Asset Files (pending)
- `framepilot-logo-full.svg`
- `framepilot-logo-icon.svg`
- `framepilot-logo-wordmark.svg`
- `framepilot-icon-32.png`
- `framepilot-icon-64.png`
- `framepilot-icon-512.png`

---

## UI Components

### Primary Button
- Background: `#FF6B35`
- Text: `#0A0A0B` (dark)
- Border radius: 8px
- Hover: `#FFFFFF` background with orange glow

### Secondary Button
- Background: `#1A1A1D`
- Border: 1px solid `#2A2A2E`
- Text: `#FFFFFF`
- Hover: Border color `#6B6B70`

### Cards
- Background: `#111113` or `#151517`
- Border: 1px solid `#2A2A2E`
- Border radius: 12px

### Form Inputs
- Background: `#1A1A1D`
- Border: 1px solid `#2A2A2E`
- Border radius: 8px
- Focus: Border color `#FF6B35`

### Progress Indicators
- Use orange accent `#FF6B35`
- Pulse animation for processing states

---

## CSS Variables

```css
:root {
    --orange: #FF6B35;
    --orange-dim: #E55A2B;
    --orange-glow: rgba(255, 107, 53, 0.15);
    --orange-glow-strong: rgba(255, 107, 53, 0.3);
    --bg-primary: #0A0A0B;
    --bg-secondary: #111113;
    --bg-tertiary: #1A1A1D;
    --bg-card: #151517;
    --border: #2A2A2E;
    --text-primary: #FFFFFF;
    --text-secondary: #A0A0A5;
    --text-dim: #6B6B70;
    --success: #22C55E;
    --error: #EF4444;
    --warning: #F59E0B;
}
```

---

## Contact

**Brand Owner:** ContentHype Pty Ltd
**Website:** framepilot.com
**Email:** support@framepilot.com
