# Word Animation Settings Plan

## Goal

Implement selectable non-Matrix word reveal animations for assistant message text, based on the supplied HTML reference. Users should be able to switch between `Claude-like`, `Clean Professional`, and `None` from settings. Matrix is explicitly out of scope.

## Current Context

- `frontend/src/components/chat/StreamedText.tsx` currently reveals assistant text by character count and shows a pulsing cursor while active.
- `frontend/src/components/chat/MessageBubble.tsx` renders `StreamedText` for the latest assistant message only.
- `frontend/src/components/settings/AppearanceSettings.tsx` already contains appearance controls and is the right location for this user-facing setting.
- `frontend/src/theme/ThemeProvider.tsx` persists theme preferences in `localStorage`; word animation preference can follow the same lightweight pattern.
- `frontend/src/hooks/useReducedMotion.ts` exists and must continue to disable animations when the user prefers reduced motion.

## Decisions

- Add exactly these animation modes:
  - `claude`: word-by-word reveal with subtle upward movement and blur fade.
  - `clean`: word-by-word reveal with opacity and letter-spacing settle.
  - `none`: immediate text render, no reveal cursor.
- Do not implement or expose Matrix.
- Store the preference in `localStorage` under a stable key such as `wordAnimationStyle`.
- Default to `claude` if no saved preference exists or the saved value is invalid.
- Put the selector in the existing Appearance settings tab to avoid creating a new settings tab.
- Respect `prefers-reduced-motion: reduce` by rendering full text immediately, regardless of selected style.

## Implementation Steps

1. Add a small shared animation preference module or context.
   - Define `type WordAnimationStyle = 'claude' | 'clean' | 'none'`.
   - Define valid options with labels matching the supplied HTML: `Claude-like`, `Clean Professional`, `None`.
   - Provide a helper to read and validate the `localStorage` value.
   - Prefer a React context/provider if `AppearanceSettings` and `StreamedText` need reactive updates without prop drilling.

2. Wire the provider near the app root.
   - Wrap the app content in the provider in `frontend/src/main.tsx` or `frontend/src/App.tsx`, following the current `ThemeProvider` pattern.
   - Ensure setting changes immediately affect newly rendered/active streamed text.

3. Update `AppearanceSettings.tsx`.
   - Keep the existing theme selector unchanged.
   - Add a second segmented control titled `Word animation` or `Message animation`.
   - Render three buttons for `Claude-like`, `Clean Professional`, and `None`.
   - Use existing styling conventions: `border-(--border)`, `bg-(--surface)`, `bg-(--surface-2)`, `text-(--ink)`, `text-(--ink-muted)`, and `focus-visible:ring-(--accent)`.
   - Persist via the shared setter.

4. Replace the current character-count stream logic in `StreamedText.tsx` with word-aware reveal behavior.
   - Tokenize text using whitespace-preserving splitting, for example `text.split(/(\s+)/)`.
   - Preserve spaces, tabs, and newlines exactly as text nodes or rendered tokens.
   - For `claude` and `clean`, reveal non-whitespace tokens sequentially with a timeout delay similar to the reference.
   - Append whitespace tokens without applying animation and without forcing long delays.
   - For `none`, render `text` immediately and skip the cursor.
   - Preserve the existing `active` behavior: inactive messages render immediately.
   - When `text` changes, cancel pending timeouts and restart from the beginning only when active and animated.

5. Add CSS for the two word animations.
   - Prefer `frontend/src/index.css` if global utility classes are defined there; otherwise colocate via existing CSS conventions.
   - Add `.word-reveal-claude` and `.word-reveal-clean` or similarly named classes.
   - Translate the supplied keyframes without Matrix CSS:
     - Claude: opacity 0 to 1, `translateY(8px)` to `0`, `blur(4px)` to `0`, around `0.4s`.
     - Clean: opacity and letter-spacing settle, around `0.5s`.
   - Keep colors inherited instead of hardcoding `#e2e8f0`, so messages work in light and dark themes.

6. Keep accessibility and motion behavior correct.
   - If `useReducedMotion()` returns true, render full text immediately for every style.
   - Avoid per-character spans for normal modes; use word spans only to reduce DOM size.
   - Do not add decorative emoji labels unless the existing product style supports them; prefer plain text labels in settings.

7. Clean up duplication if appropriate.
   - `frontend/src/hooks/useStreamedText.ts` appears unused by the current chat component. Do not change it unless implementation discovers an active import path or TypeScript/lint flags unused exports.

## Edge Cases

- Empty text should render nothing and not show a cursor.
- Text with multiple spaces or newlines must preserve exact formatting as currently rendered by message layout.
- Switching the setting while a message is streaming may restart or immediately affect the active animation, but it must not throw or leave stale timers.
- Existing completed messages should remain readable and can render immediately when not active.
- Invalid saved `localStorage` values should fall back to `claude`.

## Validation

1. Run the frontend typecheck/build command from `frontend/package.json`.
2. Manually verify Appearance settings shows the new word animation selector.
3. Manually verify `Claude-like` reveals assistant text word-by-word with blur/upward fade.
4. Manually verify `Clean Professional` reveals assistant text word-by-word with the letter-spacing/opacity effect.
5. Manually verify `None` renders assistant text immediately with no cursor.
6. Manually verify the selected mode persists across reloads.
7. Manually verify reduced motion renders immediately for all modes.

## Out Of Scope

- Matrix animation and Matrix UI option.
- Backend persistence or syncing this preference across devices.
- Changing model, setup, memory, privacy, or update settings behavior.
