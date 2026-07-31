import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import './DeviceApproval.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function DeviceApproval({ token, pairing, onApproved, onLogout }) {
  const [qrImage, setQrImage] = useState('')
  const [status, setStatus] = useState('Waiting for a trusted device…')

  useEffect(() => {
    if (!pairing?.pairing_uri) return
    QRCode.toDataURL(pairing.pairing_uri, {
      width: 240,
      margin: 2,
      color: { dark: '#101622', light: '#ffffff' },
      errorCorrectionLevel: 'M',
    }).then(setQrImage).catch(() => setStatus('Could not render the pairing QR code.'))
  }, [pairing])

  useEffect(() => {
    let stopped = false
    const check = async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/auth/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) return
        const devices = await response.json()
        const current = devices.find((device) => device.current)
        if (current?.status === 'active' && !stopped) onApproved()
        if (current?.status === 'revoked' && !stopped) onLogout()
      } catch {
        if (!stopped) setStatus('Connection interrupted. Approval will be checked again.')
      }
    }
    const timer = window.setInterval(check, 2500)
    void check()
    return () => { stopped = true; window.clearInterval(timer) }
  }, [onApproved, onLogout, token])

  return (
    <main className="device-approval-page">
      <section className="device-approval-card">
        <span className="device-approval-kicker">NEW DEVICE REQUEST</span>
        <h1>Approve this device</h1>
        <p>Open <strong>Devices</strong> on a trusted session and scan this QR code or enter the pairing code.</p>
        <div className="pairing-qr">
          {qrImage ? <img src={qrImage} alt="Device pairing QR code" /> : <span>Preparing QR…</span>}
        </div>
        <div className="pairing-code">
          <span>PAIRING CODE</span>
          <code>{pairing?.pairing_code || 'Unavailable after reload'}</code>
        </div>
        <p className="pairing-status">{status}</p>
        <aside>
          New devices receive messages created after approval. Old history requires an explicit encrypted device-to-device transfer.
        </aside>
        <button type="button" className="register-btn" onClick={onLogout}>Cancel and sign out</button>
      </section>
    </main>
  )
}
