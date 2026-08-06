# Backend privacy boundary

The backend is an MLS Delivery Service. It accepts only versioned routing
metadata and opaque MLS wire bytes. Pydantic rejects additional JSON fields,
including plaintext message content. The WebSocket is server-originated only
and rejects every client event. It never logs received frames.

Encrypted attachment uploads accept only ciphertext and `chat_id`; filename,
MIME type, AES key, nonce, dimensions, and plaintext checksum are rejected and
must remain inside the MLS application payload. Object storage always receives
`application/octet-stream`.

Database migrations remove plaintext message/receipt tables and group names.
Privacy tests assert that rejected sentinels create no MLS row, WebSocket
plaintext frames are not processed, attachment metadata is rejected, and media
storage contains exactly the uploaded ciphertext.
