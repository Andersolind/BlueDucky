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
npm run dev:https    # HTTPS dev server — needed to use the mic from ANOTHER device
npm run build        # production build to dist/
npm run preview      # serve the build
npm run typecheck    # tsc --noEmit
npm test             # vitest: modem loopback, challenges, 200-game sim
```

## Online multiplayer (WebRTC)

Real browser-to-browser play over WebRTC data channels, with a tiny WebSocket
**signaling** server that only brokers the connection handshake (game traffic is
peer-to-peer). The game is **host-authoritative**: the host runs the engine and
drives the bots; guests send their actions and render the host's snapshots.

**Run it (two terminals):**

```bash
npm run signal        # signaling server on ws://0.0.0.0:8080
npm run dev:https     # the app over HTTPS (WebRTC + mic need a secure context)
```

1. **Host:** open the app → **🌐 Host online game** → a 4-letter **room code** appears.
2. **Guests:** open the app → type the code → **Join**. They show up in the host's roster.
3. **Host:** press **Start** — empty seats are filled with AI agents. Everyone plays
   their own seat on their turn; the notebook is private per player.

**Networking notes**
- Same Wi-Fi / LAN works out of the box (guests reach the host's signaling server
  by hostname).
- Over the **internet**, deploy `server/signaling.mjs` somewhere public and set
  `VITE_SIGNAL_URL=wss://your-server` when building. Restrictive/symmetric NATs
  may also need a **TURN** server (public STUN alone isn't always enough) — add
  its `urls`/credentials to the `ICE` list in `src/net/webrtc.ts`.
- Privacy is honor-system: hands and per-seat notebooks live in the shared state
  the host broadcasts, so a determined player could read them via devtools. Fine
  for playing with friends; not hardened against cheating.

### Using the microphone from another device

`getUserMedia` only works in a **secure context**. `http://localhost` counts as
secure, but `http://<your-LAN-ip>` does **not** — that's why the mic fails when
you open the network URL on a phone. Run `npm run dev:https` and open the
`https://<ip>:5173` network URL; the browser warns once about the self-signed
cert (accept it) and the mic works.

## How to play

First, pick a **clearance level** (Rookie / Field Agent / Black-Ops) — it scales
how hard the clue challenges are. Then each agent is dealt a **playing token**
(a car, a person, or a gadget) with a slot-machine reveal.

The board is a **Monopoly-style ring of 24 tiles** rendered in 3D (toggle
2D/3D top-right), laid out over **real Mimico streets and schools** (Royal York
Road, Lake Shore Blvd W, Bishop Allen Academy, David Hornell School, …). You hop
clockwise around it, and the tile you land on decides what happens.

The **devices** carry an acoustic-hardware **tier** (◆ basic … ◆◆◆ black-ops)
and the band/technique they work on — shown in your notebook and on the cards.

1. **Roll & hop.** Roll a die and move that many tiles clockwise. Tokens hop
   tile-by-tile. Passing/landing on **Field HQ (GO)** earns you free intel.
2. **Land on a LOCATION tile → suggest.** You can only investigate the room you
   land on: name a suspect + device and rivals must secretly reveal a card that
   disproves you. Cards shown to you are auto-marked in your **Detective
   Notebook**.
3. **Land on an INTEL / corner tile → clue challenge.** Solve a quick cipher,
   number pattern, or signals-intel quiz. Crack it and the game rules a random
   *innocent* card off your notebook (it never touches a real solution card, so
   it speeds deduction without handing you the win).
4. **Land on a SIGNAL NODE (or a room) → ultrasonic sweep.** Opens your mic and
   listens. If the true bug is an *active emitter* planted in your room, you'll
   hear it, and the notebook auto-rules-out the impossible devices/locations. If
   a co-located player broadcasts the beacon from the **Signal Lab**, you get a
   *live contact*.
5. **Accuse** when sure. Right = case closed, you win. Wrong = you're burned and
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
