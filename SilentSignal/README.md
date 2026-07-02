# SilentSignal — Hunt the Eavesdropper

A **Clue-style deduction game** where a hidden operative has planted a bug and is
quietly exfiltrating audio. Players deduce **who** (the eavesdropper), **which
device** (the "weapon"), and **which location** (the "room") — before their rivals
do.

The twist: the game's signature move is a real **ultrasonic sweep**. The same
data-over-sound modem that powers it is a hardened, browser-native descendant of
the Python `decode_ultrasonic_signal` script in this repo — carrier in the
18–21 kHz band, a preamble/START marker, and byte framing, but with robust
multi-tone FSK + Goertzel decoding instead of coherent BPSK-by-polarity.

Everything runs **entirely in the browser**. No server, no accounts, no infra.

## Run it

```bash
cd SilentSignal
npm install
npm run dev          # http://localhost:5173
```

```bash
npm run build        # production build to dist/
npm run preview      # serve the build
npm run typecheck    # tsc --noEmit
```

## How to play

1. **Roll & move** through the building's 3×3 of rooms (center room has secret
   corridors). You can only investigate the room your agent stands in.
2. **Suggest** a suspect + device in your current room. Rivals must secretly
   reveal a card that disproves you — narrowing the truth. Cards shown to you are
   auto-marked in your **Detective Notebook**.
3. **Ultrasonic sweep** (once per turn): opens your mic and listens. If the true
   bug is an *active emitter* and it's planted in your room, you'll hear it — and
   the notebook auto-rules-out the impossible devices/locations. If a co-located
   player broadcasts the beacon from the **Signal Lab**, you get a *live contact*.
4. **Accuse** when sure. Right = case closed, you win. Wrong = you're burned and
   out of the hunt (but still must disprove others).

Rival agents are bots with real deduction: they track cards shown to them, infer
from un-disproved suggestions, and commit to an accusation as the field narrows.

## The Signal Lab (the tech showcase)

Open **⚡ Signal Lab** from the top bar to use the modem directly:

- **Transmit** any short text as an 18–21 kHz FSK burst.
- **Receive** decodes live from the mic.
- **Two-device demo:** open the page on a phone and a laptop, start the mic on
  one, hit Transmit on the other. This is genuine acoustic data transfer — the
  browser cousin of the repo's Python ultrasonic decoder.

## Architecture

```
src/
  audio/
    ultrasonic.ts     # the modem: synthesize() + decodeSamples() (pure, DOM-free)
                      #   + UltrasonicTransmitter / UltrasonicReceiver (Web Audio)
    useUltrasonic.ts  # React hook wrapping the modem (shared app-wide)
  game/
    types.ts          # GameState, Player, Suggestion, ...
    data.ts           # suspects / devices / locations + board graph
    engine.ts         # pure game logic: dealing, suggest/disprove, accuse, bot AI
  components/         # Lobby, Board, Notebook, Feed, Modals, SweepPanel, SignalLab
  App.tsx             # top-level state + bot-turn driver
```

The modem's `synthesize()` / `decodeSamples()` are pure functions with no DOM
dependency, which makes the whole encode→decode path loopback-testable without a
microphone.

## Verification

Two headless checks were run against the core logic (bundled with esbuild, run in
Node):

- **Engine:** 300 randomized full games — all terminate, solution cards are never
  dealt into a hand, and every game produces a winner.
- **Modem:** encode→decode loopback across multiple strings, clean and degraded
  (white noise, attenuation, DC offset, and a silent lead-in that forces real
  START detection) — 15/15 exact round-trips.

## Notes & limits

- Ultrasonic reception needs **microphone permission** and works best in a quiet
  room at moderate volume. Some laptop mics/speakers roll off above ~19 kHz; if
  detection is flaky, lower `baseFreq`/`step` in `DEFAULT_CONFIG`
  (`src/audio/ultrasonic.ts`).
- Multiplayer here is **local**: pass-and-play vs. bots, plus real same-room
  ultrasonic contact between co-located devices. Global online play would need a
  signaling/relay server, which is intentionally out of scope for this
  server-free build.
- Uses a `ScriptProcessorNode` for mic capture for maximum browser compatibility;
  it's deprecated in favor of `AudioWorklet` but is the simplest reliable option.
