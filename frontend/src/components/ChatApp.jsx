import { useEffect, useMemo, useRef, useState } from 'react'
import { useTheme } from '../ThemeContext'
import {
  Avatar,
  ChatHeader,
  ContactListItem,
  EmptyState,
  Icon,
  MessageActions,
  MessageComposer,
  MessageStatus,
  Modal,
  SearchInput,
} from './MessengerUI'
import './ChatApp.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS_URL = API_URL
  ? API_URL.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`

function readOutbox(login) {
  try {
    return JSON.parse(localStorage.getItem(`outbox:${login}`) || '[]')
  } catch {
    return []
  }
}

function writeOutbox(login, items) {
  localStorage.setItem(`outbox:${login}`, JSON.stringify(items))
}

function chatTitle(chat, currentLogin) {
  if (chat.type === 'group') {
    return chat.name || `Group #${chat.id}`
  }
  return chat.members.find((member) => member !== currentLogin) || `Chat #${chat.id}`
}

function messageTime(timestamp) {
  if (!timestamp) return ''
  const sqlTime = timestamp.match(/\d{4}-\d{2}-\d{2} (\d{2}:\d{2})/)
  if (sqlTime) return sqlTime[1]
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return timestamp
  return parsed.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function ChatApp({ token, login, onLogout }) {
  const { theme, toggle } = useTheme()
  const [chats, setChats] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [selectedChatId, setSelectedChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [replyingTo, setReplyingTo] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [inputText, setInputText] = useState('')
  const [error, setError] = useState('')
  const [wsReady, setWsReady] = useState(false)
  const [historyRefresh, setHistoryRefresh] = useState(0)
  const [profile, setProfile] = useState({ login, display_name: '', bio: '', avatar_url: null })
  const [profileOpen, setProfileOpen] = useState(false)
  const [groupDialogOpen, setGroupDialogOpen] = useState(false)
  const [groupName, setGroupName] = useState('')
  const [groupAvatar, setGroupAvatar] = useState(null)
  const [memberDialog, setMemberDialog] = useState(null)
  const [memberLogin, setMemberLogin] = useState('')
  const [mainMenuOpen, setMainMenuOpen] = useState(false)
  const [chatMenuOpen, setChatMenuOpen] = useState(false)
  const [editingMessage, setEditingMessage] = useState(null)
  const [editText, setEditText] = useState('')
  const wsRef = useRef(null)
  const selectedChatIdRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const prependingHistoryRef = useRef(false)
  const outboxRef = useRef(readOutbox(login))
  const reconnectTimerRef = useRef(null)
  const readReceiptsRef = useRef(new Set())

  const authHeaders = useMemo(
    () => ({ Authorization: `Bearer ${token}` }),
    [token]
  )

  const conversations = useMemo(() => {
    const existingDmUsers = new Set()
    const existingChats = chats.map((chat) => {
      if (chat.type === 'dm') {
        const otherLogin = chat.members.find((member) => member !== login)
        if (otherLogin) existingDmUsers.add(otherLogin)
      }
      return {
        key: `chat-${chat.id}`,
        chatId: chat.id,
        label: chatTitle(chat, login),
        userLogin: null,
        avatarUrl: chat.avatar_url,
        type: chat.type,
        memberRoles: chat.member_roles,
        historyVisibility: chat.history_visibility,
        memberCount: chat.members.length,
      }
    })
    const newDirectChats = searchResults
      .filter((user) => !existingDmUsers.has(user.login))
      .map((user) => ({
        key: `user-${user.login}`,
        chatId: null,
        label: user.login,
        userLogin: user.login,
        avatarUrl: user.avatar_url,
        type: 'dm',
        memberRoles: null,
        historyVisibility: null,
        memberCount: 2,
      }))
    return [...existingChats, ...newDirectChats]
  }, [chats, login, searchResults])

  const selectedConversation = conversations.find(
    (conversation) => conversation.chatId === selectedChatId
  )
  const selectedGroupRole = selectedConversation?.memberRoles?.[login]

  useEffect(() => {
    selectedChatIdRef.current = selectedChatId
  }, [selectedChatId])

  useEffect(() => {
    if (prependingHistoryRef.current) {
      prependingHistoryRef.current = false
      return
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    let cancelled = false

    const loadWorkspace = async () => {
      try {
        const [dmResponse, groupsResponse, invitationsResponse, profileResponse] = await Promise.all([
          fetch(`${API_URL}/api/v1/chats/dm`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups/invitations/pending`, {
            headers: authHeaders,
          }),
          fetch(`${API_URL}/api/v1/users/me`, { headers: authHeaders }),
        ])
        if (dmResponse.status === 401) {
          onLogout()
          return
        }
        if (!dmResponse.ok || !groupsResponse.ok || !invitationsResponse.ok || !profileResponse.ok) {
          throw new Error('Could not load conversations')
        }

        const chatData = [
          ...await groupsResponse.json(),
          ...await dmResponse.json(),
        ]
        const invitationData = await invitationsResponse.json()
        const profileData = await profileResponse.json()
        if (cancelled) return
        setChats(chatData)
        setInvitations(invitationData)
        setProfile(profileData)
        setSelectedChatId((currentId) => {
          if (chatData.some((chat) => chat.id === currentId)) return currentId
          return chatData[0]?.id ?? null
        })
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      }
    }

    loadWorkspace()
    return () => {
      cancelled = true
    }
  }, [authHeaders, onLogout])

  useEffect(() => {
    const query = searchQuery.trim()
    if (query.length < 2) {
      return undefined
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/v1/users/search?q=${encodeURIComponent(query)}`,
          { headers: authHeaders, signal: controller.signal }
        )
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) throw new Error('Search failed')
        setSearchResults(await response.json())
      } catch (searchError) {
        if (searchError.name !== 'AbortError') setError(searchError.message)
      }
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [authHeaders, onLogout, searchQuery])

  useEffect(() => {
    if (selectedChatId === null) {
      return undefined
    }

    let cancelled = false
    const loadMessages = async () => {
      try {
        const response = await fetch(
          `${API_URL}/api/v1/chats/${selectedChatId}/messages`,
          { headers: authHeaders }
        )
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) throw new Error('Could not load messages')
        const data = await response.json()
        if (!cancelled) {
          const pending = outboxRef.current.filter(
            (message) => message.chat_id === selectedChatId
          )
          setMessages([...data.items, ...pending])
          setNextCursor(data.next_cursor)
          setError('')
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      }
    }

    // A chat change must discard the previous chat before the async page arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages([])
    setNextCursor(null)
    loadMessages()
    return () => {
      cancelled = true
    }
  }, [authHeaders, historyRefresh, onLogout, selectedChatId])

  const loadOlderMessages = async () => {
    if (!nextCursor || selectedChatId === null || loadingOlder) return
    setLoadingOlder(true)
    try {
      const response = await fetch(
        `${API_URL}/api/v1/chats/${selectedChatId}/messages?cursor=${
          encodeURIComponent(nextCursor)
        }`,
        { headers: authHeaders }
      )
      if (!response.ok) throw new Error('Could not load message history')
      const data = await response.json()
      prependingHistoryRef.current = true
      setMessages((previous) => [...data.items, ...previous])
      setNextCursor(data.next_cursor)
    } catch (historyError) {
      setError(historyError.message)
    } finally {
      setLoadingOlder(false)
    }
  }

  useEffect(() => {
    let stopped = false
    let reconnectAttempt = 0

    const updateMessageStatus = (clientId, status, serverData = null) => {
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId
          ? { ...message, ...serverData, status }
          : message
      )))
    }

    const connect = () => {
      if (stopped) return
      const ws = new WebSocket(
        `${WS_URL}/api/v1/realtime/ws`,
        [`bearer.${token}`]
      )
      wsRef.current = ws
      setWsReady(false)

      ws.onopen = () => {
        reconnectAttempt = 0
        setWsReady(true)
        setError('')
        for (const pending of outboxRef.current) {
          updateMessageStatus(pending.client_id, 'sending')
          ws.send(JSON.stringify({
            type: 'send_message',
            chat_id: pending.chat_id,
            text: pending.content,
            client_id: pending.client_id,
            reply_to_server_seq: pending.reply_to_server_seq,
          }))
        }
        setHistoryRefresh((value) => value + 1)
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        setWsReady(false)
        for (const pending of outboxRef.current) {
          updateMessageStatus(pending.client_id, 'failed')
        }
        if (!stopped) {
          const delay = Math.min(1000 * (2 ** reconnectAttempt), 30000)
          reconnectAttempt += 1
          reconnectTimerRef.current = window.setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        setError('Connection lost — messages will remain queued')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'error') {
            setError(data.detail || 'Message was not sent')
            return
          }
          if (data.type === 'message_ack') {
            outboxRef.current = outboxRef.current.filter(
              (item) => item.client_id !== data.client_id
            )
            writeOutbox(login, outboxRef.current)
            updateMessageStatus(data.client_id, 'sent', data)
            return
          }
          if (data.type === 'message_status') {
            updateMessageStatus(data.client_id, data.status)
            return
          }
          if (data.type === 'message_updated') {
            setMessages((previous) => previous.map((message) => (
              message.chat_id === data.chat_id
              && message.server_seq === data.server_seq
                ? { ...message, ...data }
                : message
            )))
            return
          }
          if (data.type === 'message_deleted') {
            setMessages((previous) => previous.map((message) => (
              message.chat_id === data.chat_id
              && message.server_seq === data.server_seq
                ? { ...message, content: '', deleted_at: data.deleted_at }
                : message
            )))
            return
          }
          if (data.type === 'message') {
            ws.send(JSON.stringify({
              type: 'delivered',
              chat_id: data.chat_id,
              server_seq: data.server_seq,
            }))
            if (data.chat_id === selectedChatIdRef.current) {
              ws.send(JSON.stringify({
                type: 'read',
                chat_id: data.chat_id,
                server_seq: data.server_seq,
              }))
              setMessages((previous) => (
                previous.some((message) => message.id === data.id)
                  ? previous
                  : [...previous, data]
              ))
            }
            setError('')
          }
        } catch {
          setError('The server returned an invalid response')
        }
      }
    }

    connect()
    return () => {
      stopped = true
      window.clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [login, token])

  useEffect(() => {
    const ws = wsRef.current
    if (!wsReady || !ws || selectedChatId === null) return
    for (const message of messages) {
      const key = `${message.chat_id}:${message.server_seq}`
      if (
        message.sender !== login
        && message.server_seq
        && !readReceiptsRef.current.has(key)
      ) {
        readReceiptsRef.current.add(key)
        ws.send(JSON.stringify({
          type: 'read',
          chat_id: message.chat_id,
          server_seq: message.server_seq,
        }))
      }
    }
  }, [login, messages, selectedChatId, wsReady])

  const selectConversation = async (conversation) => {
    setError('')
    if (conversation.chatId !== null) {
      setSelectedChatId(conversation.chatId)
      return
    }

    try {
      const response = await fetch(`${API_URL}/api/v1/chats/dm`, {
        method: 'POST',
        headers: {
          ...authHeaders,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ login: conversation.userLogin }),
      })
      if (response.status === 401) {
        onLogout()
        return
      }
      if (!response.ok) throw new Error('Could not create the conversation')
      const chat = await response.json()
      setChats((previous) => (
        previous.some((item) => item.id === chat.id)
          ? previous
          : [chat, ...previous]
      ))
      setSelectedChatId(chat.id)
      setSearchQuery('')
      setSearchResults([])
    } catch (createError) {
      setError(createError.message)
    }
  }

  const sendMessage = (event) => {
    event?.preventDefault()
    const ws = wsRef.current
    const text = inputText.trim()
    if (
      !text
      || selectedChatId === null
    ) {
      return
    }

    const clientId = crypto.randomUUID()
    const pendingMessage = {
      id: `pending:${clientId}`,
      chat_id: selectedChatId,
      sender: login,
      content: text,
      client_id: clientId,
      server_seq: null,
      timestamp: new Date().toISOString(),
      status: 'sending',
      reply_to_server_seq: replyingTo?.server_seq ?? null,
      reply_to_sender: replyingTo?.sender ?? null,
      reply_to_content: replyingTo?.content ?? null,
    }
    outboxRef.current = [...outboxRef.current, pendingMessage]
    writeOutbox(login, outboxRef.current)
    setMessages((previous) => [...previous, pendingMessage])
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'send_message',
        chat_id: selectedChatId,
        text,
        client_id: clientId,
        reply_to_server_seq: replyingTo?.server_seq ?? null,
      }))
    }
    window.setTimeout(() => {
      if (outboxRef.current.some((item) => item.client_id === clientId)) {
        setMessages((previous) => previous.map((message) => (
          message.client_id === clientId
            ? { ...message, status: 'failed' }
            : message
        )))
      }
    }, 10000)
    setInputText('')
    setReplyingTo(null)
    inputRef.current?.focus()
  }

  const editMessage = (message) => {
    setEditingMessage(message)
    setEditText(message.content)
  }

  const submitMessageEdit = async (event) => {
    event.preventDefault()
    if (!editText.trim() || !editingMessage) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/${editingMessage.chat_id}/messages/${editingMessage.server_seq}`,
      {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editText.trim() }),
      }
    )
    if (!response.ok) {
      setError('Could not edit the message')
      return
    }
    setEditingMessage(null)
    setEditText('')
  }

  const deleteMessage = async (message) => {
    if (!window.confirm('Delete this message?')) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/${message.chat_id}/messages/${message.server_seq}`,
      { method: 'DELETE', headers: authHeaders }
    )
    if (!response.ok) setError('Could not delete the message')
  }

  const blockSelectedUser = async () => {
    const otherLogin = selectedConversation?.label
    if (!otherLogin || !window.confirm(`Block ${otherLogin}?`)) return
    const response = await fetch(
      `${API_URL}/api/v1/users/${encodeURIComponent(otherLogin)}/block`,
      { method: 'POST', headers: authHeaders }
    )
    if (response.ok) {
      setError(`${otherLogin} has been blocked`)
    } else {
      setError('Could not block the user')
    }
  }

  const createGroup = async (event) => {
    event.preventDefault()
    if (!groupName.trim()) return
    const response = await fetch(`${API_URL}/api/v1/chats/groups`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: groupName.trim(), avatar_url: null }),
    })
    if (!response.ok) {
      setError('Could not create the group')
      return
    }
    let group = await response.json()
    if (groupAvatar) {
      const formData = new FormData()
      formData.append('avatar', groupAvatar)
      const avatarResponse = await fetch(
        `${API_URL}/api/v1/chats/groups/${group.id}/avatar`,
        { method: 'POST', headers: authHeaders, body: formData }
      )
      if (avatarResponse.ok) group = await avatarResponse.json()
    }
    setChats((previous) => [group, ...previous])
    setSelectedChatId(group.id)
    setGroupName('')
    setGroupAvatar(null)
    setGroupDialogOpen(false)
  }

  const groupMemberAction = async (action, loginValue) => {
    if (!loginValue || !selectedChatId) return
    const paths = {
      invite: `invitations`,
      add: `members`,
      remove: `members/${encodeURIComponent(loginValue)}`,
    }
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}/${paths[action]}`,
      {
        method: action === 'remove' ? 'DELETE' : 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: action === 'remove' ? undefined : JSON.stringify({ login: loginValue }),
      }
    )
    setError(response.ok ? 'Group updated' : 'Member operation failed')
    if (response.ok && action === 'add') {
      const group = await response.json()
      setChats((previous) => previous.map((item) => (
        item.id === group.id ? group : item
      )))
    }
    if (response.ok) {
      setMemberDialog(null)
      setMemberLogin('')
    }
  }

  const acceptInvitation = async (invitation) => {
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/invitations/${invitation.id}/accept`,
      { method: 'POST', headers: authHeaders }
    )
    if (!response.ok) {
      setError('Could not accept the invitation')
      return
    }
    const group = await response.json()
    setInvitations((previous) => previous.filter(
      (item) => item.id !== invitation.id
    ))
    setChats((previous) => [group, ...previous])
  }

  const transferOwnership = async (newOwner) => {
    if (!newOwner || !selectedChatId) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}/owner`,
      {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ login: newOwner }),
      }
    )
    if (!response.ok) {
      setError('Could not transfer group ownership')
      return
    }
    const group = await response.json()
    setChats((previous) => previous.map((item) => (
      item.id === group.id ? group : item
    )))
    setError(`Ownership transferred to ${newOwner}`)
    setMemberDialog(null)
    setMemberLogin('')
  }

  const saveProfile = async (event) => {
    event.preventDefault()
    let response = await fetch(`${API_URL}/api/v1/users/me`, {
      method: 'PATCH',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: profile.display_name || null,
        bio: profile.bio || null,
      }),
    })
    if (!response.ok) {
      setError('Could not update profile')
      return
    }
    let updatedProfile = await response.json()
    const avatarFile = event.currentTarget.elements.avatar.files[0]
    if (avatarFile) {
      const formData = new FormData()
      formData.append('avatar', avatarFile)
      response = await fetch(`${API_URL}/api/v1/users/me/avatar`, {
        method: 'POST',
        headers: authHeaders,
        body: formData,
      })
      if (!response.ok) {
        setError('Profile saved, but avatar upload failed')
        return
      }
      updatedProfile = await response.json()
    }
    setProfile(updatedProfile)
    setProfileOpen(false)
  }

  const leaveGroup = async () => {
    if (!selectedChatId || !window.confirm('Leave this group?')) return
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}/leave`,
      { method: 'DELETE', headers: authHeaders }
    )
    if (!response.ok) {
      setError(
        selectedGroupRole === 'owner'
          ? 'Transfer ownership before leaving'
          : 'Could not leave the group'
      )
      return
    }
    setChats((previous) => previous.filter((item) => item.id !== selectedChatId))
    setSelectedChatId(null)
    setMessages([])
  }

  const toggleHistoryVisibility = async () => {
    if (!selectedChatId) return
    const historyVisibility = (
      selectedConversation.historyVisibility === 'all' ? 'since_join' : 'all'
    )
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}`,
      {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ history_visibility: historyVisibility }),
      }
    )
    if (!response.ok) {
      setError('Could not update history access')
      return
    }
    const group = await response.json()
    setChats((previous) => previous.map((item) => (
      item.id === group.id ? group : item
    )))
  }

  const handleLogout = () => {
    wsRef.current?.close()
    onLogout()
  }

  const handleSearchChange = (event) => {
    const value = event.target.value
    setSearchQuery(value)
    if (value.trim().length < 2) setSearchResults([])
  }

  const showConversationList = () => {
    setSelectedChatId(null)
    setMessages([])
    setChatMenuOpen(false)
  }

  return (
    <div className={`chat-container ${selectedChatId !== null ? 'mobile-chat-open' : ''}`}>
      <aside className="channel-panel" aria-label="Conversations">
        <header className="channel-header">
          <button className="brand-menu icon-button" type="button" onClick={() => setMainMenuOpen((value) => !value)} aria-label="Main menu"><Icon name="menu" /></button>
          <div className="channel-brand">
            <h1><span className="brand-diamond" />Secure Messenger</h1>
            <span>PRIVATE COMMUNICATION</span>
          </div>
          <button className="new-chat-button icon-button" type="button" onClick={() => setGroupDialogOpen(true)} aria-label="Create group"><Icon name="compose" /></button>
          {mainMenuOpen && (
            <div className="main-menu">
              <button type="button" onClick={() => { setGroupDialogOpen(true); setMainMenuOpen(false) }}>New group</button>
              <button type="button" onClick={() => { setProfileOpen(true); setMainMenuOpen(false) }}>My profile</button>
              <button type="button" onClick={toggle}>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</button>
              <button type="button" className="danger-action" onClick={handleLogout}>Sign out</button>
            </div>
          )}
        </header>

        <div className="user-search"><SearchInput value={searchQuery} onChange={handleSearchChange} /></div>
        <nav className="channel-list">
          {conversations.map((conversation) => (
            <ContactListItem
              key={conversation.key}
              conversation={conversation}
              active={selectedChatId === conversation.chatId && conversation.chatId !== null}
              onSelect={() => selectConversation(conversation)}
            />
          ))}
        </nav>

        {invitations.map((invitation) => (
          <button
            type="button"
            className="invitation-item"
            key={invitation.id}
            onClick={() => acceptInvitation(invitation)}
          >
            Accept: {invitation.group_name}
          </button>
        ))}

        <button className="user-bar" type="button" onClick={() => setProfileOpen(true)}>
          <Avatar name={profile.display_name || login} size={42} src={profile.avatar_url} />
          <div className="user-bar__info">
            <div className="user-bar__name">{profile.display_name || login}</div>
            <div className="user-bar__status">@{login}</div>
          </div>
          <Icon name="more" size={17} />
        </button>
      </aside>

      <main className="chat-panel">
        <ChatHeader
          conversation={selectedConversation}
          connected={wsReady}
          onBack={showConversationList}
          onMenu={() => setChatMenuOpen((value) => !value)}
        />
        <div className="chat-menu-anchor">
            {chatMenuOpen && selectedConversation && (
              <div className="chat-actions-menu">
                {selectedConversation.type === 'dm' && <button type="button" onClick={blockSelectedUser}>Block user</button>}
                {selectedConversation.type === 'group' && ['owner', 'admin'].includes(selectedGroupRole) && (
                  <>
                    <button type="button" onClick={() => { setMemberDialog('invite'); setChatMenuOpen(false) }}>Invite member</button>
                    <button type="button" onClick={() => { setMemberDialog('add'); setChatMenuOpen(false) }}>Add member</button>
                    <button type="button" onClick={() => { setMemberDialog('remove'); setChatMenuOpen(false) }}>Remove member</button>
                  </>
                )}
                {selectedGroupRole === 'owner' && (
                  <>
                    <button type="button" onClick={() => { setMemberDialog('owner'); setChatMenuOpen(false) }}>Transfer ownership</button>
                    <button type="button" onClick={toggleHistoryVisibility}>Change history access</button>
                  </>
                )}
                {selectedConversation.type === 'group' && <button type="button" className="danger-action" onClick={leaveGroup}>Leave group</button>}
              </div>
            )}
        </div>

        <div className="messages-list" key={selectedChatId ?? 'empty'}>
          {!wsReady && <div className="offline-banner">Connection interrupted. Queued messages will retry automatically.</div>}
          {error && <p className="error-message">{error}</p>}
          {nextCursor && (
            <button
              type="button"
              className="load-older"
              onClick={loadOlderMessages}
              disabled={loadingOlder}
            >
              {loadingOlder ? 'Loading…' : 'Load earlier messages'}
            </button>
          )}
          {messages.length === 0 && <EmptyState hasConversation={selectedChatId !== null} />}
          {messages.map((message, index) => {
            const own = message.sender === login
            const previous = messages[index - 1]
            const grouped = previous?.sender === message.sender
              && previous.kind !== 'system'
              && message.kind !== 'system'
            if (message.kind === 'system') {
              return (
                <div key={message.id} className="system-message">
                  <span>{message.content}</span>
                  <time>{messageTime(message.timestamp)}</time>
                </div>
              )
            }
            return (
              <div
                key={message.id}
                className={`message ${own ? 'own' : 'other'} ${grouped ? 'grouped' : ''}`}
              >
                {!own && !grouped ? <Avatar name={message.sender} size={36} /> : !own ? <span className="message-avatar-spacer" /> : null}
                <div className="message__body">
                  {message.reply_to_server_seq && (
                    <div className="message__reply">
                      <strong>{message.reply_to_sender}</strong>
                      <span>
                        {message.reply_to_content || 'Message deleted'}
                      </span>
                    </div>
                  )}
                  <div className="message__bubble">
                    <span className="message__text">
                      {message.deleted_at ? 'Message deleted' : message.content}
                    </span>
                  </div>
                  <span className="message__time">
                    {messageTime(message.timestamp)}
                    {message.edited_at && !message.deleted_at && <span className="edited-label">edited</span>}
                    {own && <MessageStatus status={message.status} />}
                  </span>
                  {!message.deleted_at && message.server_seq && (
                    <MessageActions message={message} own={own} onReply={setReplyingTo} onEdit={editMessage} onDelete={deleteMessage} />
                  )}
                </div>
              </div>
            )
          })}
          <div ref={messagesEndRef} />
        </div>

        {replyingTo && (
          <div className="reply-composer">
            <span>
              Replying to <strong>{replyingTo.sender}</strong>:{' '}
              {replyingTo.content}
            </span>
            <button type="button" onClick={() => setReplyingTo(null)}>×</button>
          </div>
        )}
        <MessageComposer
          inputRef={inputRef}
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          onSubmit={sendMessage}
          conversation={selectedConversation}
          disabled={selectedChatId === null}
        />
      </main>

      {groupDialogOpen && (
        <Modal title="New group" onClose={() => setGroupDialogOpen(false)}>
          <form className="modal-form" onSubmit={createGroup}>
            <label className="photo-picker">
              <Avatar name={groupName || 'Group'} size={84} src={groupAvatar ? URL.createObjectURL(groupAvatar) : null} />
              <span>Choose group photo</span>
              <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setGroupAvatar(event.target.files[0] || null)} />
            </label>
            <label>Group name<input value={groupName} maxLength={255} autoFocus onChange={(event) => setGroupName(event.target.value)} placeholder="Name your group" /></label>
            <button className="primary-button" type="submit" disabled={!groupName.trim()}>Create group</button>
          </form>
        </Modal>
      )}

      {profileOpen && (
        <Modal title="Edit profile" onClose={() => setProfileOpen(false)}>
          <form className="modal-form" onSubmit={saveProfile}>
            <label className="photo-picker">
              <Avatar name={profile.display_name || login} size={92} src={profile.avatar_url} />
              <span>Upload a new photo</span>
              <input name="avatar" type="file" accept="image/jpeg,image/png,image/webp" />
            </label>
            <label>Display name<input value={profile.display_name || ''} maxLength={64} onChange={(event) => setProfile((value) => ({ ...value, display_name: event.target.value }))} /></label>
            <label>Bio<textarea value={profile.bio || ''} maxLength={160} rows={3} onChange={(event) => setProfile((value) => ({ ...value, bio: event.target.value }))} placeholder="A few words about you" /></label>
            <div className="profile-login">@{login}</div>
            <button className="primary-button" type="submit">Save changes</button>
          </form>
        </Modal>
      )}

      {memberDialog && (
        <Modal title={memberDialog === 'owner' ? 'Transfer ownership' : `${memberDialog[0].toUpperCase()}${memberDialog.slice(1)} member`} onClose={() => setMemberDialog(null)}>
          <form className="modal-form" onSubmit={(event) => {
            event.preventDefault()
            if (memberDialog === 'owner') transferOwnership(memberLogin)
            else groupMemberAction(memberDialog, memberLogin)
          }}>
            <label>Username<input value={memberLogin} autoFocus onChange={(event) => setMemberLogin(event.target.value)} placeholder="@username" /></label>
            <button className="primary-button" type="submit" disabled={!memberLogin.trim()}>Continue</button>
          </form>
        </Modal>
      )}

      {editingMessage && (
        <Modal title="Edit message" onClose={() => setEditingMessage(null)}>
          <form className="modal-form" onSubmit={submitMessageEdit}>
            <label>Message<textarea value={editText} rows={4} autoFocus maxLength={16384} onChange={(event) => setEditText(event.target.value)} /></label>
            <button className="primary-button" type="submit" disabled={!editText.trim()}>Save message</button>
          </form>
        </Modal>
      )}
    </div>
  )
}

export default ChatApp
