# Visual review checklist (per screenshot)

Look at each screenshot and answer these. Name the config file, for example `dark.png`.

## Status bar & navigation bar
- Are status bar icons (clock, battery) readable? Dark icons on a light background and light icons on a dark one. White icons on a white top bar is a classic bug.
- Does the area behind the status bar match the top app bar or the screen background? A grey, black or different-colored strip means edge-to-edge or insets are handled wrong.
- Is any title, back button or search field drawn under the status bar or a camera cutout?
- Is the bottom navigation bar, a FAB or a button hidden behind the gesture bar or the 3-button nav bar?
- Does the nav bar area color match the bottom of the screen?

## Theme colors
- Do primary buttons, links, switches and app bars use the brand color from the theme? A Material-default purple/blue or a random color means a hardcoded or dynamic color.
- In `dark.png`: is any card, dialog or background still white? Is any text dark-on-dark or light-on-light? Do icons disappear because they're black on dark?
- Are any elements on one screen inconsistent with the others (two different greens, mixed corner radius)?

## Fonts & text
- In `font.png` (font scale 1.3 or 2.0): is any text cut, overlapping, clipped inside a fixed-height button or chip, or pushed off-screen? Is there anything you can't scroll to?
- Is the font family the same everywhere? A serif or system font in one place among custom fonts is a bug.
- Are the heading, body and caption sizes consistent?

## Layout on different devices
- `small.png` (about 320dp wide): horizontal overflow, buttons squeezed, text wrapping badly, content cut on the right?
- `tablet.png` (800dp wide): is content stretched edge-to-edge in an ugly way (very long lines, giant buttons), or is it a tiny phone layout in the corner? Are images blurry or pixelated?
- `land.png`: can the content scroll? Are forms or bottom buttons cut off? Does the app keep its state, or reset to the first screen?

## General
- Empty states: blank white screen with no message or loading indicator.
- Placeholder or debug text left in ("Lorem ipsum", "TODO", "test", raw IDs, `null`).
- Images missing (grey boxes) or stretched.
- Elements misaligned (different left margins on the same screen).

## Ads
- Does a banner or native ad cover any app content, list items or buttons? That's a policy violation (high).
- Is there at least about 8dp of clear space between an ad and any button? Ads touching buttons cause accidental clicks.
- Is the banner under the gesture bar or nav bar, or cut at the screen edge (`tablet.png`, `land.png`)?
- Does a full-screen ad (interstitial or app-open) appear right at launch or when a screen opens (`default.png`, `explore/screen_01.png`)? That's an unexpected interstitial.
- Debug builds should show the "Test Ad" label. A real ad in a debug build means live IDs are used while testing.

## Orientation (explore/screen_NN.png vs screen_NN_land.png)
- Is the landscape version usable: does it scroll, are buttons reachable, is nothing cut off?
- Was typed text or the selected state kept (also see the Rotation table in results.md)?
- Does the layout use the extra width sensibly, or is it a stretched phone layout?

## Offline (screens/offline.png)
- Does the screen show a clear "No internet" message with a retry, or a blank screen, endless spinner, or crash?
