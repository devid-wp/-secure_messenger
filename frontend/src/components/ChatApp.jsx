import { useState, useEffect, useRef } from 'react'
import './ChatApp.css'

function ChatApp({ token, login, onLogout }) {
  const [contacts] = useState(['Alice', 'Bob', 'Charlie', 'Diana'])
  const [selectedContact, setSelectedContact] = useState('Alice')
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [ws, setWs] = useState(null)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    if (selectedContact) {
      fetchMessages()
    }
  }, [selectedContact])

  const fetchMessages = async () => {
    try {
      const response = await fetch('http://localhost:8000/messages', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setMessages(data)
      }
    } catch (err) {
      console.error('Error fetching messages:', err)
    }
  }

  const connectWebSocket = () => {
    try {
      const wsUrl = `ws://localhost:8000/ws/${token}`
      const newWs = new WebSocket(wsUrl)

      newWs.onopen = () => {
        console.log('WebSocket connected')
      }

      newWs.onmessage = (event) => {
        const data = JSON.parse(event.data)
        setMessages((prev) => [...prev, { from: data.from, text: data.text, timestamp: new Date().toLocaleTimeString() }])
      }

      newWs.onerror = (err) => {
        console.error('WebSocket error:', err)
      }

      newWs.onclose = () => {
        console.log('WebSocket disconnected')
      }

      setWs(newWs)
    } catch (err) {
      console.error('Error connecting WebSocket:', err)
    }
  }

  useEffect(() => {
    connectWebSocket()
    return () => {
      if (ws) {
        ws.close()
      }
    }
  }, [token])

  const sendMessage = (e) => {
    e.preventDefault()
    if (!inputText.trim() || !ws || ws.readyState !== WebSocket.OPEN) {
      return
    }

    const message = {
      to: selectedContact,
      text: inputText,
    }

    ws.send(JSON.stringify(message))
    setMessages((prev) => [
      ...prev,
      { from: login, text: inputText, timestamp: new Date().toLocaleTimeString() },
    ])
    setInputText('')
  }

  const handleLogout = () => {
    if (ws) {
      ws.close()
    }
    onLogout()
  }

  return (
    <div className="chat-container">
      <div className="contacts-panel">
        <div className="contacts-header">
          <h2>Чаты</h2>
          <button className="logout-btn" onClick={handleLogout}>
            Выйти
          </button>
        </div>
        <div className="contacts-list">
          {contacts.map((contact) => (
            <div
              key={contact}
              className={`contact-item ${selectedContact === contact ? 'active' : ''}`}
              onClick={() => setSelectedContact(contact)}
            >
              {contact}
            </div>
          ))}
        </div>
      </div>

      <div className="chat-panel">
        <div className="chat-header">
          <h3>{selectedContact}</h3>
          <p className="user-info">Вы: {login}</p>
        </div>

        <div className="messages-list">
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`message ${msg.from === login ? 'own' : 'other'}`}
            >
              <span className="message-text">{msg.text}</span>
              <span className="message-time">{msg.timestamp}</span>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <form className="message-input-form" onSubmit={sendMessage}>
          <input
            type="text"
            placeholder="Напишите сообщение..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={ws?.readyState !== WebSocket.OPEN}
          />
          <button type="submit" disabled={ws?.readyState !== WebSocket.OPEN}>
            Отправить
          </button>
        </form>
      </div>
    </div>
  )
}

export default ChatApp
