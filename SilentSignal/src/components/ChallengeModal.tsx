import { useState } from 'react'
import { ChallengeState } from '../game/types'
import { checkChallenge } from '../game/challenges'

interface Props {
  challenge: ChallengeState
  onResolve: (success: boolean) => void
}

/**
 * The clue-challenge you face when landing on an INTEL / corner tile. Solve it
 * to earn intel (an innocent card ruled off your notebook).
 */
export default function ChallengeModal({ challenge, onResolve }: Props) {
  const [input, setInput] = useState('')
  const [result, setResult] = useState<null | boolean>(null)

  const submit = (value: string) => {
    const ok = checkChallenge(challenge, value)
    setResult(ok)
    window.setTimeout(() => onResolve(ok), 1100)
  }

  return (
    <div className="overlay">
      <div className="modal challenge">
        <div className="ch-tag">CLUE CHALLENGE</div>
        <h2>{challenge.title}</h2>
        {result === null ? (
          <>
            <p className="modal-sub">
              Crack it to earn intel — <b>{challenge.reward}</b>
            </p>

            <div className="ch-prompt">{challenge.prompt}</div>
            {challenge.hint && <div className="ch-hint">💡 {challenge.hint}</div>}

            {challenge.kind === 'quiz' ? (
              <div className="ch-options">
                {challenge.options!.map((opt) => (
                  <button key={opt} className="ch-option" onClick={() => submit(opt)}>
                    {opt}
                  </button>
                ))}
              </div>
            ) : (
              <form
                className="ch-form"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (input.trim()) submit(input)
                }}
              >
                <input
                  autoFocus
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={challenge.kind === 'sequence' ? 'next number…' : 'decoded word…'}
                  inputMode={challenge.kind === 'sequence' ? 'numeric' : 'text'}
                />
                <button className="primary" type="submit" disabled={!input.trim()}>
                  Submit
                </button>
              </form>
            )}

            <div className="modal-actions">
              <button className="ghost" onClick={() => onResolve(false)}>
                Skip (no intel)
              </button>
            </div>
          </>
        ) : (
          <div className={`ch-result ${result ? 'good' : 'bad'}`}>
            <div className="ch-result-badge">{result ? '✓ DECRYPTED' : '✗ SCRAMBLED'}</div>
            <p>
              {result
                ? challenge.reward
                : `The answer was "${challenge.answer}". No intel this time.`}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
