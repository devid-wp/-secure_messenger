/**
 * Fixed full-screen animated backdrop with three blurred gradient orbs
 * and a subtle grid overlay. Lives behind the app content.
 */
export default function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <div className="orb orb--a" />
      <div className="orb orb--b" />
      <div className="orb orb--c" />
    </div>
  )
}
