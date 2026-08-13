import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar,
  ChatHeader,
  ConversationSkeleton,
  ContactListItem,
  EmptyState,
  Icon,
  MessageActions,
  MessageComposer,
  MessageStatus,
  MessagesSkeleton,
  MobileNavigation,
  Modal,
  SearchInput,
} from './MessengerUI'
import './ChatApp.css'
import {
  decryptEnvelope,
  e2eeAvailable,
  encryptAndPublish,
  preflightApplicationPayload,
  removeRevokedDevice,
  removeMlsMembers,
  rotateMlsEpoch,
  resynchronizeMlsGroup,
  synchronizeMlsGroup,
} from '../crypto/e2eeMessaging'
import { listMlsCredentials } from '../crypto/mlsRuntimeBridge'
import { decryptAttachment, encryptAttachment, MAX_ATTACHMENT_BYTES } from '../crypto/attachmentCrypto'
import { createSafetyCode } from '../crypto/safetyCode'
import { applyMessageLifecycle } from '../crypto/messageLifecycle'
import { mergeMessageFeed, replacePendingStatus } from '../crypto/messageFeed'
import { MLS_ERROR_CODES } from '../crypto/mlsErrors'
import QRCode from 'qrcode'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS_URL = API_URL
  ? API_URL.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
const MAX_AVATAR_BYTES = 50 * 1024 * 1024
const AVATAR_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const IMAGE_ATTACHMENT_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const QUICK_EMOJI = ['😀', '😂', '❤️', '👍', '🔥', '🎉', '😎', '🤝', '👀', '✅', '🔒', '✨', '🙏', '💜', '🚀', '🫡']

function readOutbox(login) {
  void login
  return []
}

function writeOutbox(login, items) {
  // Plaintext drafts/outbox entries must never be persisted by the renderer.
  void login
  void items
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

function AuthenticatedMedia({ path, token, alt, className }) {
  const [source, setSource] = useState('')

  useEffect(() => {
    if (!path) return undefined
    let active = true
    let objectUrl = ''
    fetch(path.startsWith('/') ? `${API_URL}${path}` : path, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error('Media unavailable')
        return response.blob()
      })
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setSource(objectUrl)
      })
      .catch(() => {
        if (active) setSource('')
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path, token])

  return source
    ? <img className={className} src={source} alt={alt} />
    : <span className={`${className} media-loading`} aria-label="Loading media" />
}

function EncryptedAttachment({ message, token }) {
  const [state, setState] = useState({ loading: true, source: '', error: '' })
  const descriptor = useMemo(() => message.attachment_descriptor, [message.attachment_descriptor])
  const objectUrlRef = useRef('')

  useEffect(() => {
    if (!message.attachment?.content_url || !descriptor) {
      return undefined
    }
    let active = true
    const previousUrl = objectUrlRef.current
    objectUrlRef.current = ''
    const decrypt = async () => {
      try {
        const response = await fetch(`${API_URL}${message.attachment.content_url}`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: 'no-store',
        })
        if (!response.ok) throw new Error('Download failed')
        // Stream the ciphertext instead of buffering the whole file:
        // `decryptAttachment` reads the body in chunks and only builds
        // the plaintext Blob after the GCM tag and SHA-256 match.
        const plaintext = await decryptAttachment(await response.blob(), descriptor)
        if (!active) {
          plaintext.fill(0)
          return
        }
        // The plaintext Blob and its URL are created only after a
        // successful decryption + integrity check, so the browser never
        // surfaces unauthenticated bytes to <img>/<a>.
        const objectUrl = URL.createObjectURL(new Blob(
          [plaintext],
          { type: descriptor.media_type || 'application/octet-stream' },
        ))
        plaintext.fill(0)
        objectUrlRef.current = objectUrl
        setState({ loading: false, source: objectUrl, error: '' })
      } catch {
        if (active) {
          setState({ loading: false, source: '', error: 'Could not decrypt attachment' })
        }
      }
    }
    decrypt()
    return () => {
      active = false
      if (previousUrl) URL.revokeObjectURL(previousUrl)
      const latest = objectUrlRef.current
      objectUrlRef.current = ''
      if (latest) URL.revokeObjectURL(latest)
    }
  }, [descriptor, message.attachment, token])

  if (!message.attachment?.content_url || !descriptor) {
    return <span className="encrypted-media-error">Attachment key is unavailable</span>
  }
  if (state.loading) return <span className="encrypted-media-loading">Decrypting…</span>
  if (state.error) return <span className="encrypted-media-error">{state.error}</span>
  if (message.kind === 'image') {
    return <img className="message__encrypted-image" src={state.source} alt={descriptor.name || 'Encrypted attachment'} />
  }
  return (
    <a className="message__file-download" href={state.source} download={descriptor.name || 'attachment'}>
      <Icon name="attach" />
      <span><strong>{descriptor.name || 'Encrypted file'}</strong><small>Download decrypted file</small></span>
    </a>
  )
}

async function cropSticker(file, zoom) {
  const bitmap = await createImageBitmap(file)
  const sourceSize = Math.min(bitmap.width, bitmap.height) / zoom
  const sourceX = (bitmap.width - sourceSize) / 2
  const sourceY = (bitmap.height - sourceSize) / 2
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 512
  const context = canvas.getContext('2d')
  context.drawImage(
    bitmap,
    sourceX,
    sourceY,
    sourceSize,
    sourceSize,
    0,
    0,
    512,
    512
  )
  bitmap.close()
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('Could not crop image')),
      'image/webp',
      0.92
    )
  })
}

function ChatApp({ token, login, deviceId, onLogout }) {
  const [chats, setChats] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [workspaceLoading, setWorkspaceLoading] = useState(true)
  const [searchLoading, setSearchLoading] = useState(false)
  const [selectedChatId, setSelectedChatId] = useState(null)
  const [messages, setMessages] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [replyingTo, setReplyingTo] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [blockedUsers, setBlockedUsers] = useState([])
  const [securityEvents, setSecurityEvents] = useState([])
  const [inputText, setInputText] = useState('')
  const [error, setError] = useState('')
  const [mlsBlockedChats, setMlsBlockedChats] = useState(() => new Set())

  useEffect(() => {
    const handleMlsError = (event) => {
      const code = event.detail?.code
      if (event.detail?.blocked && event.detail?.chatId !== undefined) {
        setMlsBlockedChats((current) => new Set(current).add(String(event.detail.chatId)))
      }
      if (code && ![MLS_ERROR_CODES.DUPLICATE, MLS_ERROR_CODES.STALE_EPOCH].includes(code)) {
        setError(`Encrypted envelope rejected (${code}).`)
      }
    }
    window.addEventListener('secure-messenger:mls-error', handleMlsError)
    return () => window.removeEventListener('secure-messenger:mls-error', handleMlsError)
  }, [])
  const [wsReady, setWsReady] = useState(false)
  const [historyRefresh, setHistoryRefresh] = useState(0)
  const [profile, setProfile] = useState({ id: null, login, username: login.toLowerCase(), display_name: '', bio: '', avatar_url: null })
  const [profileOpen, setProfileOpen] = useState(false)
  const [devicesOpen, setDevicesOpen] = useState(false)
  const [devices, setDevices] = useState([])
  const [deviceBusy, setDeviceBusy] = useState(false)
  const [verification, setVerification] = useState(null)
  const [verificationBusy, setVerificationBusy] = useState(false)
  const [profileAvatar, setProfileAvatar] = useState(null)
  const [profileAvatarPreview, setProfileAvatarPreview] = useState(null)
  const [profileFormError, setProfileFormError] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [stickerPickerOpen, setStickerPickerOpen] = useState(false)
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [attachmentBusy, setAttachmentBusy] = useState(false)
  const [stickerManagerOpen, setStickerManagerOpen] = useState(false)
  const [stickerPacks, setStickerPacks] = useState([])
  const [discoverPacks, setDiscoverPacks] = useState([])
  const [ownedPacks, setOwnedPacks] = useState([])
  const [selectedPackId, setSelectedPackId] = useState('')
  const [packDraft, setPackDraft] = useState({
    title: '',
    slug: '',
    visibility: 'private',
  })
  const [stickerFile, setStickerFile] = useState(null)
  const [stickerPreview, setStickerPreview] = useState('')
  const [stickerZoom, setStickerZoom] = useState(1)
  const [stickerBusy, setStickerBusy] = useState(false)
  const [stickerError, setStickerError] = useState('')
  const [groupDialogOpen, setGroupDialogOpen] = useState(false)
  const [groupName, setGroupName] = useState('')
  const [groupAvatar, setGroupAvatar] = useState(null)
  const [memberDialog, setMemberDialog] = useState(null)
  const [memberLogin, setMemberLogin] = useState('')
  const [memberBusy, setMemberBusy] = useState(false)
  const [mainMenuOpen, setMainMenuOpen] = useState(false)
  const [chatMenuOpen, setChatMenuOpen] = useState(false)
  const [editingMessage, setEditingMessage] = useState(null)
  const [editText, setEditText] = useState('')
  const wsRef = useRef(null)
  const selectedChatIdRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const attachmentInputRef = useRef(null)
  const prependingHistoryRef = useRef(false)
  const outboxRef = useRef(readOutbox(login))
  const reconnectTimerRef = useRef(null)
  const decryptedEnvelopesRef = useRef(new Map())
  const sentSinceUpdateRef = useRef(new Map())
  const receiptedMessagesRef = useRef(new Set())
  const profileAvatarPreviewRef = useRef(null)
  const stickerPreviewRef = useRef(null)

  const authHeaders = useMemo(
    () => ({ Authorization: `Bearer ${token}` }),
    [token]
  )

  useEffect(() => () => {
    if (profileAvatarPreviewRef.current) {
      URL.revokeObjectURL(profileAvatarPreviewRef.current)
    }
    if (stickerPreviewRef.current) {
      URL.revokeObjectURL(stickerPreviewRef.current)
    }
  }, [])

  useEffect(() => {
    const closeFloatingPanels = (event) => {
      if (event.key !== 'Escape') return
      setMainMenuOpen(false)
      setChatMenuOpen(false)
      setStickerPickerOpen(false)
      setEmojiPickerOpen(false)
    }
    window.addEventListener('keydown', closeFloatingPanels)
    return () => window.removeEventListener('keydown', closeFloatingPanels)
  }, [])

  const conversations = useMemo(() => {
    const existingDmUsers = new Set()
    const normalizedQuery = searchQuery.trim().toLowerCase()
    const existingChats = chats.map((chat) => {
      const peer = chat.type === 'dm' ? chat.peer : null
      if (chat.type === 'dm') {
        const otherLogin = chat.members.find((member) => member !== login)
        if (otherLogin) existingDmUsers.add(otherLogin)
      }
      return {
        key: `chat-${chat.id}`,
        chatId: chat.id,
        label: peer?.display_name || peer?.username || chatTitle(chat, login),
        username: peer?.username || null,
        stableUserId: peer?.id || null,
        userLogin: peer?.login || null,
        isSearchResult: false,
        avatarUrl: chat.avatar_url,
        type: chat.type,
        memberRoles: chat.member_roles,
        historyVisibility: chat.history_visibility,
        memberCount: chat.members.length,
        lastMessage: chat.last_message,
        unreadCount: chat.unread_count || 0,
      }
    }).filter((conversation) => (
      !normalizedQuery || conversation.label.toLowerCase().includes(normalizedQuery)
    ))
    const newDirectChats = searchResults
      .filter((user) => !existingDmUsers.has(user.login))
      .map((user) => ({
        key: `user-${user.login}`,
        chatId: null,
        label: user.display_name || user.username,
        username: user.username,
        stableUserId: user.id,
        userLogin: user.login,
        isSearchResult: true,
        avatarUrl: user.avatar_url,
        type: 'dm',
        memberRoles: null,
        historyVisibility: null,
        memberCount: 2,
        lastMessage: null,
        unreadCount: 0,
      }))
    return [...existingChats, ...newDirectChats].sort((left, right) => {
      if (left.isSearchResult || right.isSearchResult) return left.isSearchResult ? -1 : 1
      const leftTime = left.lastMessage?.timestamp || ''
      const rightTime = right.lastMessage?.timestamp || ''
      return rightTime.localeCompare(leftTime)
    })
  }, [chats, login, searchQuery, searchResults])

  const totalUnread = useMemo(
    () => chats.reduce((total, chat) => total + (chat.unread_count || 0), 0),
    [chats]
  )

  const selectedConversation = conversations.find(
    (conversation) => conversation.chatId === selectedChatId
  )
  const selectedGroupRole = selectedConversation?.memberRoles?.[login]
  const knownPeople = useMemo(() => {
    const people = new Map()
    for (const chat of chats) {
      if (chat.type === 'dm' && chat.peer) people.set(chat.peer.login, chat.peer)
    }
    return [...people.values()].sort((left, right) => (
      (left.display_name || left.username).localeCompare(right.display_name || right.username)
    ))
  }, [chats])
  const memberCandidates = useMemo(() => {
    if (!memberDialog || !selectedConversation) return []
    const memberLogins = new Set(Object.keys(selectedConversation.memberRoles || {}))
    if (['invite', 'add'].includes(memberDialog)) {
      return knownPeople.filter((person) => !memberLogins.has(person.login))
    }
    return [...memberLogins]
      .filter((member) => member !== login)
      .map((member) => knownPeople.find((person) => person.login === member) || {
        id: null,
        login: member,
        username: member,
        display_name: null,
        avatar_url: null,
      })
  }, [knownPeople, login, memberDialog, selectedConversation])
  const selectedUserIsBlocked = Boolean(
    selectedConversation?.userLogin
    && blockedUsers.some((user) => user.login === selectedConversation.userLogin)
  )

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
        const [dmResponse, groupsResponse, invitationsResponse, profileResponse, blocksResponse, securityResponse] = await Promise.all([
          fetch(`${API_URL}/api/v1/chats/dm`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/chats/groups/invitations/pending`, {
            headers: authHeaders,
          }),
          fetch(`${API_URL}/api/v1/users/me`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/users/blocks`, { headers: authHeaders }),
          fetch(`${API_URL}/api/v1/e2ee/security-events`, { headers: authHeaders }),
        ])
        if (dmResponse.status === 401) {
          onLogout()
          return
        }
        if (!dmResponse.ok || !groupsResponse.ok || !invitationsResponse.ok || !profileResponse.ok || !blocksResponse.ok || !securityResponse.ok) {
          throw new Error('Could not load conversations')
        }

        const groups = await groupsResponse.json()
        for (const group of groups) {
          try {
            await synchronizeMlsGroup(token, deviceId, group.id)
            const response = await fetch(
              `${API_URL}/api/v1/e2ee/chats/${group.id}/envelopes?after=0`,
              { headers: authHeaders }
            )
            if (!response.ok) continue
            const envelopes = await response.json()
            for (const envelope of envelopes) {
              if (envelope.content_type !== 'application') continue
              const item = await decryptEnvelope(group.id, envelope)
              if (item?.type === 'group_metadata' && item.name) {
                group.name = item.name
              }
            }
          } catch (mlsError) {
            if (![MLS_ERROR_CODES.DUPLICATE, MLS_ERROR_CODES.STALE_EPOCH].includes(mlsError.code)) {
              setError(`Encrypted group metadata rejected (${mlsError.code || 'protocol_violation'})`)
            }
          }
        }
        const chatData = [...groups, ...await dmResponse.json()]
        const invitationData = await invitationsResponse.json()
        const profileData = await profileResponse.json()
        const blockedPeople = await blocksResponse.json()
        const securityData = await securityResponse.json()
        if (cancelled) return
        setChats(chatData)
        setInvitations(invitationData)
        setProfile(profileData)
        setBlockedUsers(blockedPeople)
        setSecurityEvents(securityData)
        setSelectedChatId((currentId) => {
          if (chatData.some((chat) => chat.id === currentId)) return currentId
          return chatData[0]?.id ?? null
        })
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      } finally {
        if (!cancelled) setWorkspaceLoading(false)
      }
    }

    loadWorkspace()
    return () => {
      cancelled = true
    }
  }, [authHeaders, deviceId, onLogout, token])

  useEffect(() => {
    const query = searchQuery.trim()
    if (query.length < 2) {
      return undefined
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setSearchLoading(true)
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
      } finally {
        setSearchLoading(false)
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

    const activeChatId = selectedChatId
    let cancelled = false
    const loadMessages = async () => {
      setMessagesLoading(true)
      try {
        await synchronizeMlsGroup(token, deviceId, activeChatId)
        const response = await fetch(
          `${API_URL}/api/v1/e2ee/chats/${activeChatId}/envelopes?after=0`,
          { headers: authHeaders }
        )
        if (response.status === 401) {
          onLogout()
          return
        }
        if (!response.ok) throw new Error('Could not load messages')
        const envelopes = await response.json()
        const lifecycleEvents = []
        const mlsFailures = []
        for (const envelope of envelopes) {
          if (envelope.content_type !== 'application') continue
          let item = decryptedEnvelopesRef.current.get(envelope.id)
          if (!item) {
            try {
              item = await decryptEnvelope(activeChatId, envelope)
              if (item) decryptedEnvelopesRef.current.set(envelope.id, item)
            } catch (mlsError) {
              if (![MLS_ERROR_CODES.DUPLICATE, MLS_ERROR_CODES.STALE_EPOCH].includes(mlsError.code)) {
                mlsFailures.push(mlsError.code || MLS_ERROR_CODES.PROTOCOL_VIOLATION)
              }
            }
          }
          if (item) lifecycleEvents.push({
            item,
            envelope: { id: `mls:${envelope.id}`, timestamp: envelope.created_at, mls_epoch: envelope.epoch },
          })
        }
        const decrypted = applyMessageLifecycle(lifecycleEvents)
        for (const message of decrypted) {
          if (message.sender_device_id === deviceId || receiptedMessagesRef.current.has(message.client_id)) continue
          try {
            for (const state of ['delivered', 'read']) {
              await encryptAndPublish(token, activeChatId, {
                client_id: crypto.randomUUID(), sent_at: new Date().toISOString(),
                operation: 'receipt', target_client_id: message.client_id, state,
              })
            }
            receiptedMessagesRef.current.add(message.client_id)
          } catch { mlsFailures.push('receipt_publish_failed') }
        }
        if (!cancelled) {
          const pending = outboxRef.current.filter(
            (message) => message.chat_id === activeChatId
          )
          setMessages(mergeMessageFeed(decrypted, pending))
          setNextCursor(null)
          setChats((previous) => previous.map((chat) => (
            chat.id === activeChatId ? { ...chat, unread_count: 0 } : chat
          )))
          setError(mlsFailures.length ? `Rejected ${mlsFailures.length} unverifiable encrypted envelope(s).` : '')
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      } finally {
        if (!cancelled) setMessagesLoading(false)
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
  }, [authHeaders, deviceId, historyRefresh, onLogout, selectedChatId, token])

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
        setHistoryRefresh((value) => value + 1)
        for (const pending of [...outboxRef.current]) {
          void (async () => {
            try {
              await synchronizeMlsGroup(token, deviceId, pending.chat_id)
              const envelope = await encryptAndPublish(token, pending.chat_id, pending)
              decryptedEnvelopesRef.current.set(envelope.id, pending)
              outboxRef.current = outboxRef.current.filter((item) => item.client_id !== pending.client_id)
              updateMessageStatus(pending.client_id, 'sent', {
                id: `mls:${envelope.id}`, timestamp: envelope.created_at, mls_epoch: envelope.epoch,
              })
            } catch (retryError) {
              updateMessageStatus(pending.client_id, 'failed')
              setError(retryError.message || 'Encrypted retry failed')
            }
          })()
        }
      }

      ws.onclose = (closeEvent) => {
        if (wsRef.current === ws) wsRef.current = null
        setWsReady(false)
        for (const pending of outboxRef.current) {
          updateMessageStatus(pending.client_id, 'failed')
        }
        if (closeEvent.code === 4003) {
          onLogout()
          return
        }
        if (!stopped) {
          const delay = Math.min(1000 * (2 ** reconnectAttempt), 30000)
          reconnectAttempt += 1
          reconnectTimerRef.current = window.setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        // The close handler updates connection state and retries automatically.
        // Avoid showing the same outage as both a banner and an error.
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'error') {
            setError(data.detail || 'Message was not sent')
            return
          }
          if (data.type === 'security_event') {
            if (data.event === 'device_revoked') {
              setError(`Security alert: ${data.device_name} was revoked. MLS removal is required before encrypted sending resumes.`)
            } else if (data.event === 'device_approved') {
              setError(`New device approved: ${data.device_name}. Its MLS add commit is pending.`)
            } else if (data.event === 'fingerprint_changed') {
              setError('Security warning: a contact device fingerprint changed. Verify the safety code before continuing.')
            }
            return
          }
          if (data.type === 'mls_envelope') {
            setHistoryRefresh((value) => value + 1)
            return
          }
          if (data.type === 'message_ack') {
            outboxRef.current = outboxRef.current.filter(
              (item) => item.client_id !== data.client_id
            )
            writeOutbox(login, outboxRef.current)
            updateMessageStatus(data.client_id, 'sent', data)
            setChats((previous) => previous.map((chat) => (
              chat.id === data.chat_id
                ? {
                    ...chat,
                    last_message: {
                      sender: login,
                      kind: data.kind || 'text',
                      content: data.content || '',
                      timestamp: data.timestamp,
                    },
                  }
                : chat
            )))
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
            setChats((previous) => previous.map((chat) => (
              chat.id === data.chat_id
                ? {
                    ...chat,
                    last_message: {
                      sender: data.sender,
                      kind: data.kind,
                      content: data.content,
                      timestamp: data.timestamp,
                    },
                    unread_count: data.chat_id === selectedChatIdRef.current
                      ? 0
                      : (chat.unread_count || 0) + 1,
                  }
                : chat
            )))
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
  }, [deviceId, login, onLogout, token])

  const selectConversation = async (conversation) => {
    setError('')
    if (conversation.chatId !== null) {
      setSelectedChatId(conversation.chatId)
      setChats((previous) => previous.map((chat) => (
        chat.id === conversation.chatId ? { ...chat, unread_count: 0 } : chat
      )))
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

  const sendMessage = async (event) => {
    event?.preventDefault()
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
      kind: 'text',
      client_id: clientId,
      server_seq: null,
      timestamp: new Date().toISOString(),
      status: 'sending',
      reply_to_server_seq: replyingTo?.server_seq ?? null,
      reply_to_client_id: replyingTo?.client_id ?? null,
      reply_to_sender: replyingTo?.sender ?? null,
      reply_to_content: replyingTo?.content ?? null,
    }
    try {
      preflightApplicationPayload(pendingMessage, deviceId)
    } catch (validationError) {
      setError(validationError.message || 'Message exceeds encrypted payload limits')
      return
    }
    outboxRef.current = [...outboxRef.current, pendingMessage]
    writeOutbox(login, outboxRef.current)
    setMessages((previous) => [...previous, pendingMessage])
    setInputText('')
    setReplyingTo(null)
    inputRef.current?.focus()
    try {
      if (!e2eeAvailable()) throw new Error('Sending is disabled: native MLS is unavailable')
      await synchronizeMlsGroup(token, deviceId, selectedChatId)
      const envelope = await encryptAndPublish(token, selectedChatId, pendingMessage)
      decryptedEnvelopesRef.current.set(envelope.id, pendingMessage)
      outboxRef.current = outboxRef.current.filter((item) => item.client_id !== clientId)
      const sentCount = (sentSinceUpdateRef.current.get(selectedChatId) || 0) + 1
      sentSinceUpdateRef.current.set(selectedChatId, sentCount)
      if (sentCount >= 100) {
        await rotateMlsEpoch(token, selectedChatId)
        sentSinceUpdateRef.current.set(selectedChatId, 0)
      }
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId
          ? { ...message, id: `mls:${envelope.id}`, status: 'sent', timestamp: envelope.created_at, mls_epoch: envelope.epoch }
          : message
      )))
    } catch (sendError) {
      setError(sendError.message || 'Encrypted message could not be sent')
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId ? { ...message, status: 'failed' } : message
      )))
    }
  }

  const retryPendingMessage = async (message) => {
    if (!message?.client_id || message.status === 'sending') return
    setError('')
    setMessages((previous) => replacePendingStatus(previous, message.client_id, 'sending'))
    try {
      await synchronizeMlsGroup(token, deviceId, message.chat_id)
      const envelope = await encryptAndPublish(token, message.chat_id, message)
      decryptedEnvelopesRef.current.set(envelope.id, message)
      outboxRef.current = outboxRef.current.filter((item) => item.client_id !== message.client_id)
      setMessages((previous) => previous.map((item) => (
        item.client_id === message.client_id
          ? { ...item, id: `mls:${envelope.id}`, status: 'sent', timestamp: envelope.created_at, mls_epoch: envelope.epoch }
          : item
      )))
    } catch (retryError) {
      setMessages((previous) => replacePendingStatus(previous, message.client_id, 'failed'))
      setError(retryError.message || 'Encrypted retry failed')
    }
  }

  const resyncSelectedChat = async () => {
    if (selectedChatId === null) return
    try {
      await resynchronizeMlsGroup(token, deviceId, selectedChatId)
      setMlsBlockedChats((current) => {
        const next = new Set(current)
        next.delete(String(selectedChatId))
        return next
      })
      setError('MLS resync completed. Encrypted sending is enabled.')
      setHistoryRefresh((value) => value + 1)
    } catch (resyncError) {
      setError(resyncError.message || 'MLS resync failed; encrypted sending remains blocked')
    }
  }

  const editMessage = (message) => {
    setEditingMessage(message)
    setEditText(message.content)
  }

  const submitMessageEdit = async (event) => {
    event.preventDefault()
    if (!editText.trim() || !editingMessage) return
    try {
      await encryptAndPublish(token, editingMessage.chat_id, {
        client_id: crypto.randomUUID(),
        sent_at: new Date().toISOString(),
        operation: 'edit',
        target_client_id: editingMessage.client_id,
        content: editText.trim(),
      })
      setMessages((previous) => previous.map((message) => (
        message.client_id === editingMessage.client_id
          ? { ...message, content: editText.trim(), edited_at: new Date().toISOString() }
          : message
      )))
    } catch {
      setError('Could not edit the message')
      return
    }
    setEditingMessage(null)
    setEditText('')
  }

  const deleteMessage = async (message) => {
    if (!window.confirm('Delete this message?')) return
    try {
      await encryptAndPublish(token, message.chat_id, {
        client_id: crypto.randomUUID(),
        sent_at: new Date().toISOString(),
        operation: 'delete', target_client_id: message.client_id,
      })
      setMessages((previous) => previous.map((item) => (
        item.client_id === message.client_id
          ? { ...item, content: '', deleted_at: new Date().toISOString() }
          : item
      )))
    } catch {
      setError('Could not delete the message')
    }
  }

  const reactToMessage = async (message, emoji) => {
    try {
      await encryptAndPublish(token, message.chat_id, {
        client_id: crypto.randomUUID(), sent_at: new Date().toISOString(),
        operation: 'reaction', target_client_id: message.client_id, emoji,
      })
      setHistoryRefresh((value) => value + 1)
    } catch (reactionError) {
      setError(reactionError.message || 'Could not send encrypted reaction')
    }
  }

  const blockSelectedUser = async () => {
    const otherLogin = selectedConversation?.userLogin
    if (!otherLogin || selectedUserIsBlocked || !window.confirm(`Block @${selectedConversation.username}?`)) return
    const response = await fetch(
      `${API_URL}/api/v1/users/${encodeURIComponent(otherLogin)}/block`,
      { method: 'POST', headers: authHeaders }
    )
    if (response.ok) {
      setBlockedUsers((previous) => [
        ...previous.filter((user) => user.login !== otherLogin),
        {
          id: selectedConversation.stableUserId,
          login: otherLogin,
          username: selectedConversation.username,
          display_name: selectedConversation.label,
          avatar_url: selectedConversation.avatarUrl,
        },
      ])
      setChatMenuOpen(false)
      setError(`@${selectedConversation.username} has been blocked`)
    } else {
      setError('Could not block the user')
    }
  }

  const unblockSelectedUser = async () => {
    const otherLogin = selectedConversation?.userLogin
    if (!otherLogin || !selectedUserIsBlocked) return
    const response = await fetch(
      `${API_URL}/api/v1/users/${encodeURIComponent(otherLogin)}/block`,
      { method: 'DELETE', headers: authHeaders }
    )
    if (response.ok) {
      setBlockedUsers((previous) => previous.filter((user) => user.login !== otherLogin))
      setChatMenuOpen(false)
      setError(`@${selectedConversation.username} has been unblocked`)
    } else {
      setError('Could not unblock the user')
    }
  }

  const createGroup = async (event) => {
    event.preventDefault()
    if (!groupName.trim()) return
    const response = await fetch(`${API_URL}/api/v1/chats/groups`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_url: null }),
    })
    if (!response.ok) {
      setError('Could not create the group')
      return
    }
    let group = await response.json()
    await synchronizeMlsGroup(token, deviceId, group.id)
    await encryptAndPublish(token, group.id, {
      client_id: crypto.randomUUID(),
      sent_at: new Date().toISOString(),
      operation: 'group_metadata',
      name: groupName.trim(),
    })
    group = { ...group, name: groupName.trim() }
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
    const normalizedLogin = loginValue.trim().replace(/^@/, '')
    if (!normalizedLogin || !selectedChatId || memberBusy) return
    setMemberBusy(true)
    let removedDeviceIds = []
    if (action === 'remove') {
      const directoryResponse = await fetch(
        `${API_URL}/api/v1/e2ee/chats/${selectedChatId}/devices`,
        { headers: authHeaders }
      )
      if (directoryResponse.ok) {
        const directory = await directoryResponse.json()
        removedDeviceIds = directory.devices
          .filter((device) => device.login === normalizedLogin)
          .map((device) => device.device_id)
      }
    }
    const paths = {
      invite: `invitations`,
      add: `members`,
      remove: `members/${encodeURIComponent(normalizedLogin)}`,
    }
    const response = await fetch(
      `${API_URL}/api/v1/chats/groups/${selectedChatId}/${paths[action]}`,
      {
        method: action === 'remove' ? 'DELETE' : 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: action === 'remove' ? undefined : JSON.stringify({ login: normalizedLogin }),
      }
    )
    const responseBody = response.ok ? null : await response.json().catch(() => null)
    setError(response.ok ? 'Group updated' : (responseBody?.detail || 'Member operation failed'))
    if (response.ok && action === 'add') {
      const group = await response.json()
      setChats((previous) => previous.map((item) => (
        item.id === group.id ? group : item
      )))
    }
    if (response.ok) {
      if (action === 'remove' && removedDeviceIds.length) {
        await removeMlsMembers(token, selectedChatId, removedDeviceIds)
      }
      setMemberDialog(null)
      setMemberLogin('')
    }
    setMemberBusy(false)
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

  const clearProfileAvatar = () => {
    if (profileAvatarPreviewRef.current) {
      URL.revokeObjectURL(profileAvatarPreviewRef.current)
      profileAvatarPreviewRef.current = null
    }
    setProfileAvatar(null)
    setProfileAvatarPreview(null)
  }

  const openProfile = () => {
    clearProfileAvatar()
    setProfileFormError('')
    setProfileOpen(true)
  }

  const closeProfile = () => {
    clearProfileAvatar()
    setProfileFormError('')
    setProfileOpen(false)
  }

  const refreshDevices = async () => {
    const response = await fetch(`${API_URL}/api/v1/auth/devices`, { headers: authHeaders })
    if (!response.ok) throw new Error('Could not load devices')
    const rows = await response.json()
    setDevices(rows)
    return rows
  }

  const openDevices = async () => {
    setMainMenuOpen(false)
    setDevicesOpen(true)
    try {
      await refreshDevices()
    } catch (deviceError) {
      setError(deviceError.message)
    }
  }

  const revokeTrustedDevice = async (device) => {
    if (device.status === 'revoked' || !window.confirm(`Revoke ${device.name}?`)) return
    setDeviceBusy(true)
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/devices/${device.id}`, {
        method: 'DELETE', headers: authHeaders,
      })
      if (!response.ok) throw new Error('Could not revoke device')
      if (device.current) {
        onLogout()
        return
      }
      const updatedChats = await removeRevokedDevice(token, chats.map((chat) => chat.id), device.id)
      await refreshDevices()
      setError(`Device revoked; MLS Remove Commit applied in ${updatedChats.length} conversation(s).`)
    } catch (revokeError) {
      setError(revokeError.message)
    } finally {
      setDeviceBusy(false)
    }
  }

  const openContactVerification = async () => {
    const contactLogin = selectedConversation?.userLogin
    if (!contactLogin) return
    setChatMenuOpen(false); setVerificationBusy(true)
    try {
      await synchronizeMlsGroup(token, deviceId, selectedChatId)
      const responses = await Promise.all([login, contactLogin].map((name) => fetch(
        `${API_URL}/api/v1/e2ee/users/${encodeURIComponent(name)}/identities`, { headers: authHeaders },
      )))
      if (responses.some((response) => !response.ok)) throw new Error('Could not load device identities')
      const identities = await Promise.all(responses.map((response) => response.json()))
      const code = await createSafetyCode(identities, await listMlsCredentials(selectedChatId))
      setVerification({ contactLogin, code: code.display, qr: await QRCode.toDataURL(code.qrPayload, { errorCorrectionLevel: 'M', margin: 1, width: 240 }) })
    } catch (caught) { setError(caught.message) } finally { setVerificationBusy(false) }
  }

  const acknowledgeSecurityEvent = async (eventId) => {
    const response = await fetch(`${API_URL}/api/v1/e2ee/security-events/${eventId}/acknowledge`, {
      method: 'POST', headers: authHeaders,
    })
    if (response.ok) {
      setSecurityEvents((previous) => previous.filter((event) => event.id !== eventId))
    }
  }

  const selectProfileAvatar = (event) => {
    const file = event.target.files[0] || null
    clearProfileAvatar()
    setProfileFormError('')
    if (!file) return
    if (!AVATAR_TYPES.has(file.type)) {
      setProfileFormError('Choose a JPEG, PNG, or WebP image.')
      event.target.value = ''
      return
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setProfileFormError('The photo must be 50 MB or smaller.')
      event.target.value = ''
      return
    }
    const previewUrl = URL.createObjectURL(file)
    profileAvatarPreviewRef.current = previewUrl
    setProfileAvatar(file)
    setProfileAvatarPreview(previewUrl)
  }

  const saveProfile = async (event) => {
    event.preventDefault()
    setProfileFormError('')
    setProfileSaving(true)
    try {
      if (profileAvatar) {
        const formData = new FormData()
        formData.append('avatar', profileAvatar)
        const avatarResponse = await fetch(`${API_URL}/api/v1/users/me/avatar`, {
          method: 'POST',
          headers: authHeaders,
          body: formData,
        })
        if (!avatarResponse.ok) {
          setProfileFormError('The photo could not be uploaded. Check its format and try again.')
          return
        }
      }

      const response = await fetch(`${API_URL}/api/v1/users/me`, {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: profile.username.trim().toLowerCase().replace(/^@/, ''),
          display_name: profile.display_name || null,
          bio: profile.bio || null,
        }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        setProfileFormError(body?.detail || 'The profile could not be saved. Please try again.')
        return
      }
      const updatedProfile = await response.json()
      setProfile(updatedProfile)
      setError('')
      closeProfile()
    } catch {
      setProfileFormError('The server is unavailable. Please try again.')
    } finally {
      setProfileSaving(false)
    }
  }

  const loadStickerPacks = async (scope) => {
    const response = await fetch(
      `${API_URL}/api/v1/sticker-packs?scope=${scope}`,
      { headers: authHeaders }
    )
    if (!response.ok) throw new Error('Could not load sticker packs')
    return response.json()
  }

  const openStickerPicker = async () => {
    setStickerError('')
    setStickerPickerOpen(true)
    try {
      setStickerPacks(await loadStickerPacks('library'))
    } catch (loadError) {
      setStickerError(loadError.message)
    }
  }

  const openStickerManager = async () => {
    setMainMenuOpen(false)
    setStickerError('')
    setStickerManagerOpen(true)
    try {
      const [owned, discover] = await Promise.all([
        loadStickerPacks('owned'),
        loadStickerPacks('discover'),
      ])
      setOwnedPacks(owned)
      setDiscoverPacks(discover)
      setSelectedPackId((current) => (
        current || owned[0]?.id || ''
      ))
    } catch (loadError) {
      setStickerError(loadError.message)
    }
  }

  const createStickerPack = async (event) => {
    event.preventDefault()
    setStickerBusy(true)
    setStickerError('')
    try {
      const response = await fetch(`${API_URL}/api/v1/sticker-packs`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(packDraft),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Could not create sticker pack')
      }
      setOwnedPacks((previous) => [...previous, data])
      if (data.visibility === 'public') {
        setDiscoverPacks((previous) => [...previous, data])
      }
      setSelectedPackId(data.id)
      setPackDraft({ title: '', slug: '', visibility: 'private' })
    } catch (createError) {
      setStickerError(createError.message)
    } finally {
      setStickerBusy(false)
    }
  }

  const selectStickerFile = (event) => {
    const file = event.target.files[0] || null
    if (stickerPreviewRef.current) {
      URL.revokeObjectURL(stickerPreviewRef.current)
      stickerPreviewRef.current = null
    }
    setStickerFile(null)
    setStickerPreview('')
    setStickerZoom(1)
    setStickerError('')
    if (!file) return
    if (!['image/png', 'image/webp'].includes(file.type)) {
      setStickerError('Choose a PNG or WebP image.')
      event.target.value = ''
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setStickerError('Sticker source must be 5 MB or smaller.')
      event.target.value = ''
      return
    }
    const previewUrl = URL.createObjectURL(file)
    stickerPreviewRef.current = previewUrl
    setStickerFile(file)
    setStickerPreview(previewUrl)
  }

  const uploadSticker = async (event) => {
    event.preventDefault()
    if (!selectedPackId || !stickerFile) return
    setStickerBusy(true)
    setStickerError('')
    try {
      const cropped = await cropSticker(stickerFile, stickerZoom)
      const formData = new FormData()
      formData.append('sticker', cropped, 'sticker.webp')
      const response = await fetch(
        `${API_URL}/api/v1/sticker-packs/${selectedPackId}/stickers`,
        {
          method: 'POST',
          headers: authHeaders,
          body: formData,
        }
      )
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Could not upload sticker')
      }
      setOwnedPacks((previous) => previous.map((pack) => (
        pack.id === selectedPackId
          ? { ...pack, stickers: [...pack.stickers, data] }
          : pack
      )))
      setDiscoverPacks((previous) => previous.map((pack) => (
        pack.id === selectedPackId
          ? { ...pack, stickers: [...pack.stickers, data] }
          : pack
      )))
      setStickerFile(null)
      setStickerPreview('')
      if (stickerPreviewRef.current) {
        URL.revokeObjectURL(stickerPreviewRef.current)
        stickerPreviewRef.current = null
      }
    } catch (uploadError) {
      setStickerError(uploadError.message)
    } finally {
      setStickerBusy(false)
    }
  }

  const subscribeToStickerPack = async (packId) => {
    setStickerError('')
    const response = await fetch(
      `${API_URL}/api/v1/sticker-packs/${packId}/subscription`,
      { method: 'POST', headers: authHeaders }
    )
    if (!response.ok) {
      setStickerError('Could not add sticker pack')
      return
    }
    const [owned, discover] = await Promise.all([
      loadStickerPacks('owned'),
      loadStickerPacks('discover'),
    ])
    setOwnedPacks(owned)
    setDiscoverPacks(discover)
  }

  const unsubscribeFromStickerPack = async (packId) => {
    setStickerError('')
    const response = await fetch(
      `${API_URL}/api/v1/sticker-packs/${packId}/subscription`,
      { method: 'DELETE', headers: authHeaders }
    )
    if (!response.ok) {
      setStickerError('Could not remove sticker pack')
      return
    }
    setDiscoverPacks((previous) => previous.map((pack) => (
      pack.id === packId ? { ...pack, subscribed: false } : pack
    )))
    setStickerPacks((previous) => previous.filter((pack) => pack.id !== packId))
  }

  const toggleStickerPackVisibility = async (pack) => {
    const visibility = pack.visibility === 'public' ? 'private' : 'public'
    setStickerError('')
    const response = await fetch(
      `${API_URL}/api/v1/sticker-packs/${pack.id}`,
      {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ visibility }),
      }
    )
    if (!response.ok) {
      setStickerError('Could not update pack visibility')
      return
    }
    const updated = await response.json()
    setOwnedPacks((previous) => previous.map((item) => (
      item.id === updated.id ? updated : item
    )))
    const discover = await loadStickerPacks('discover')
    setDiscoverPacks(discover)
  }

  const sendSticker = async (sticker) => {
    if (selectedChatId === null) return
    const clientId = crypto.randomUUID()
    const pendingMessage = {
      id: `pending:${clientId}`,
      chat_id: selectedChatId,
      sender: login,
      content: '',
      kind: 'sticker',
      sticker,
      client_id: clientId,
      server_seq: null,
      timestamp: new Date().toISOString(),
      status: 'sending',
      reply_to_server_seq: null,
      reply_to_sender: null,
      reply_to_content: null,
    }
    try {
      preflightApplicationPayload(pendingMessage, deviceId)
    } catch (validationError) {
      setError(validationError.message || 'Sticker exceeds encrypted payload limits')
      return
    }
    outboxRef.current = [...outboxRef.current, pendingMessage]
    writeOutbox(login, outboxRef.current)
    setMessages((previous) => [...previous, pendingMessage])
    setStickerPickerOpen(false)
    try {
      await synchronizeMlsGroup(token, deviceId, selectedChatId)
      const envelope = await encryptAndPublish(token, selectedChatId, pendingMessage)
      decryptedEnvelopesRef.current.set(envelope.id, pendingMessage)
      outboxRef.current = outboxRef.current.filter((item) => item.client_id !== clientId)
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId ? { ...message, id: `mls:${envelope.id}`, status: 'sent' } : message
      )))
      await synchronizeMlsGroup(token, deviceId, selectedChatId)
    } catch (sendError) {
      setError(sendError.message || 'Encrypted sticker could not be sent')
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId ? { ...message, status: 'failed' } : message
      )))
    }
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
    if (value.trim().length < 2) {
      setSearchResults([])
      setSearchLoading(false)
    }
  }

  const showConversationList = () => {
    setSelectedChatId(null)
    setMessages([])
    setChatMenuOpen(false)
  }

  const chooseAttachment = async (files) => {
    const file = files?.[0]
    setDragActive(false)
    if (!file) return
    if (selectedChatId === null) {
      setError('Select a conversation before attaching a file.')
      return
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setError('Attachments must be 50 MB or smaller.')
      return
    }
    setAttachmentBusy(true)
    setError('')
    let clientId = null
    try {
      const { ciphertext, descriptor } = await encryptAttachment(file)
      const form = new FormData()
      form.append('ciphertext', new Blob([ciphertext]), 'ciphertext.bin')
      form.append('chat_id', String(selectedChatId))
      const response = await fetch(`${API_URL}/api/v1/media/attachments`, {
        method: 'POST',
        headers: authHeaders,
        body: form,
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || 'Could not upload attachment')
      }
      const attachment = await response.json()
      descriptor.object_id = attachment.id
      clientId = crypto.randomUUID()
      const kind = IMAGE_ATTACHMENT_TYPES.has(file.type) ? 'image' : 'file'
      const pendingMessage = {
        id: `pending:${clientId}`,
        chat_id: selectedChatId,
        sender: login,
        content: '',
        kind,
        attachment,
        attachment_descriptor: descriptor,
        client_id: clientId,
        server_seq: null,
        timestamp: new Date().toISOString(),
        status: 'sending',
      }
      preflightApplicationPayload(pendingMessage, deviceId)
      outboxRef.current = [...outboxRef.current, pendingMessage]
      writeOutbox(login, outboxRef.current)
      setMessages((previous) => [...previous, pendingMessage])
      await synchronizeMlsGroup(token, deviceId, selectedChatId)
      const envelope = await encryptAndPublish(token, selectedChatId, pendingMessage)
      decryptedEnvelopesRef.current.set(envelope.id, pendingMessage)
      outboxRef.current = outboxRef.current.filter((item) => item.client_id !== clientId)
      setMessages((previous) => previous.map((message) => (
        message.client_id === clientId ? { ...message, id: `mls:${envelope.id}`, status: 'sent' } : message
      )))
    } catch (attachmentError) {
      setError(attachmentError.message || 'Could not encrypt attachment')
      if (clientId) setMessages((previous) => replacePendingStatus(previous, clientId, 'failed'))
    } finally {
      setAttachmentBusy(false)
    }
  }

  const handleDrop = (event) => {
    event.preventDefault()
    void chooseAttachment(event.dataTransfer.files)
  }

  const insertEmoji = (emoji) => {
    const textarea = inputRef.current
    const start = textarea?.selectionStart ?? inputText.length
    const end = textarea?.selectionEnd ?? inputText.length
    setInputText(`${inputText.slice(0, start)}${emoji}${inputText.slice(end)}`)
    setEmojiPickerOpen(false)
    window.requestAnimationFrame(() => {
      textarea?.focus()
      textarea?.setSelectionRange(start + emoji.length, start + emoji.length)
    })
  }

  return (
    <div
      className={`chat-container ${selectedChatId !== null ? 'mobile-chat-open' : ''} ${dragActive ? 'is-dragging' : ''}`}
      onDragEnter={(event) => { event.preventDefault(); setDragActive(true) }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
          setDragActive(false)
        }
      }}
      onDrop={handleDrop}
    >
      <aside className="channel-panel" aria-label="Conversations">
        <header className="channel-header">
          <button className="brand-menu icon-button" type="button" onClick={() => setMainMenuOpen((value) => !value)} aria-label="Main menu"><Icon name="menu" /></button>
          <div className="channel-brand">
            <h1><span className="brand-diamond" />Secure Messenger</h1>
            <span>PRIVATE COMMUNICATION</span>
          </div>
          <button className="new-chat-button icon-button" type="button" onClick={() => setGroupDialogOpen(true)} aria-label="Create group"><Icon name="compose" /></button>
          {mainMenuOpen && (
            <div className="main-menu" role="menu">
              <button role="menuitem" type="button" onClick={() => { setGroupDialogOpen(true); setMainMenuOpen(false) }}>New group</button>
              <button role="menuitem" type="button" onClick={() => { openProfile(); setMainMenuOpen(false) }}>My profile</button>
              <button role="menuitem" type="button" onClick={openDevices}>Devices</button>
              <button role="menuitem" type="button" onClick={openStickerManager}>Sticker packs</button>
              <button role="menuitem" type="button" className="danger-action" onClick={handleLogout}>Sign out</button>
            </div>
          )}
        </header>

        <div className="user-search"><SearchInput value={searchQuery} onChange={handleSearchChange} loading={searchLoading} /></div>
        <nav className="channel-list">
          {!workspaceLoading && conversations.length > 0 && (
            <div className="signal-index">
              <span>{searchQuery.trim() ? 'IDENTITY MATCHES' : 'SIGNAL INDEX'}</span>
              <strong>{conversations.length.toString().padStart(2, '0')}</strong>
            </div>
          )}
          {workspaceLoading && <ConversationSkeleton />}
          {!workspaceLoading && conversations.length === 0 && (
            <div className="sidebar-empty">
              <Icon name="search" />
              <strong>No conversations</strong>
              <span>Search for someone to start a private chat.</span>
            </div>
          )}
          {!workspaceLoading && conversations.map((conversation) => (
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
            Accept encrypted group invitation #{invitation.chat_id}
          </button>
        ))}

        <MobileNavigation
          unreadCount={totalUnread}
          onNewGroup={() => setGroupDialogOpen(true)}
          onProfile={openProfile}
        />
        <button className="user-bar" type="button" onClick={openProfile}>
          <Avatar name={profile.display_name || login} size={42} src={profile.avatar_url} />
          <div className="user-bar__info">
            <div className="user-bar__name">{profile.display_name || login}</div>
            <div className="user-bar__status">@{profile.username || login}</div>
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
              <div className="chat-actions-menu" role="menu">
                {selectedConversation.type === 'dm' && (
                  <button type="button" disabled={verificationBusy} onClick={openContactVerification}>Verify safety code</button>
                )}
                {selectedConversation.type === 'dm' && (
                  selectedUserIsBlocked
                    ? <button type="button" className="restore-action" onClick={unblockSelectedUser}>Unblock @{selectedConversation.username}</button>
                    : <button type="button" className="danger-action" onClick={blockSelectedUser}>Block @{selectedConversation.username}</button>
                )}
                {selectedConversation.type === 'group' && ['owner', 'admin'].includes(selectedGroupRole) && (
                  <>
                    <button type="button" onClick={() => { setMemberDialog('invite'); setChatMenuOpen(false) }}>Invite member</button>
                    <button type="button" onClick={() => { setMemberDialog('add'); setChatMenuOpen(false) }}>Add member</button>
                    <button type="button" onClick={() => { setMemberDialog('remove'); setChatMenuOpen(false) }}>Remove member</button>
                  </>
                )}
                {selectedGroupRole === 'owner' && (
                  <>
                    <div className="menu-separator" role="separator" />
                    <button type="button" onClick={() => { setMemberDialog('owner'); setChatMenuOpen(false) }}>Transfer ownership</button>
                    <button type="button" onClick={toggleHistoryVisibility}>Change history access</button>
                  </>
                )}
                {selectedConversation.type === 'group' && (
                  <>
                    <div className="menu-separator" role="separator" />
                    <button type="button" className="danger-action" onClick={leaveGroup}>Leave group</button>
                  </>
                )}
              </div>
            )}
        </div>

        <div className="messages-list" key={selectedChatId ?? 'empty'}>
          {securityEvents.map((securityEvent) => (
            <div className="security-warning" role="alert" key={securityEvent.id}>
              <Icon name="shield" />
              <span>
                <strong>Contact credential or device set changed</strong>
                <small>Device {securityEvent.device_id?.slice(0, 8) || 'unknown'} · compare the new safety code before trusting new messages.</small>
              </span>
              <button type="button" onClick={() => acknowledgeSecurityEvent(securityEvent.id)}>Reviewed</button>
            </div>
          ))}
          {mlsBlockedChats.has(String(selectedChatId)) && (
            <div className="security-warning" role="alert">
              <Icon name="shield" />
              <span>
                <strong>Encrypted sending blocked</strong>
                <small>An ambiguous MLS error requires an explicit resync. Plaintext fallback is disabled.</small>
              </span>
              <button type="button" onClick={resyncSelectedChat}>Resync MLS</button>
            </div>
          )}
          {!wsReady && <div className="offline-banner">Connection interrupted. Queued messages will retry automatically.</div>}
          {error && <p className="error-message" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss error">×</button></p>}
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
          {messagesLoading && <MessagesSkeleton />}
          {!messagesLoading && messages.length === 0 && <EmptyState conversation={selectedConversation} />}
          {!messagesLoading && messages.map((message, index) => {
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
                  {(message.reply_to_server_seq || message.reply_to_client_id) && (
                    <div className="message__reply">
                      <strong>{message.reply_to_sender}</strong>
                      <span>
                        {message.reply_to_content || 'Message deleted'}
                      </span>
                    </div>
                  )}
                  {message.deleted_at ? (
                    <div className="message__bubble">
                      <span className="message__text">Message deleted</span>
                    </div>
                  ) : message.kind === 'sticker' && message.sticker ? (
                    <div className="message__sticker">
                      <AuthenticatedMedia
                        path={message.sticker.image_url}
                        token={token}
                        alt={message.sticker.emoji || 'Sticker'}
                        className="message__sticker-image"
                      />
                    </div>
                  ) : ['image', 'file'].includes(message.kind) && message.attachment ? (
                    <div className="message__attachment">
                      <EncryptedAttachment message={message} token={token} />
                      <small className="message__attachment-mode">
                        AES-256-GCM · storage encrypted
                      </small>
                    </div>
                  ) : (
                    <div className="message__bubble">
                      <span className="message__text">{message.content}</span>
                    </div>
                  )}
                  {message.reactions?.length > 0 && <div className="message__reactions">
                    {message.reactions.map((reaction) => <span key={`${reaction.sender_device_id}:${reaction.emoji}`} title={reaction.sender}>{reaction.emoji}</span>)}
                  </div>}
                  <span className="message__time">
                    {messageTime(message.timestamp)}
                    {message.edited_at && !message.deleted_at && <span className="edited-label">edited</span>}
                    {own && <MessageStatus status={message.status} />}
                  </span>
                  {!message.deleted_at && message.client_id && (
                    <MessageActions message={message} own={own} onReply={setReplyingTo} onEdit={editMessage} onDelete={deleteMessage} onReact={reactToMessage} onRetry={retryPendingMessage} />
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
          onSticker={openStickerPicker}
          onEmoji={() => {
            setEmojiPickerOpen((value) => !value)
            setStickerPickerOpen(false)
          }}
          onAttach={() => attachmentInputRef.current?.click()}
          conversation={selectedConversation}
          disabled={selectedChatId === null || !e2eeAvailable() || mlsBlockedChats.has(String(selectedChatId))}
        />
        <input
          ref={attachmentInputRef}
          className="visually-hidden"
          type="file"
          disabled={attachmentBusy || selectedChatId === null || !e2eeAvailable() || mlsBlockedChats.has(String(selectedChatId))}
          onChange={(event) => {
            void chooseAttachment(event.target.files)
            event.target.value = ''
          }}
          tabIndex={-1}
        />
        {attachmentBusy && (
          <div className="attachment-progress" role="status">
            <span className="search-spinner" />
            Encrypting and uploading…
          </div>
        )}
        {emojiPickerOpen && (
          <div className="emoji-picker" role="dialog" aria-label="Emoji picker">
            <header><strong>Emoji</strong><span>Quick reactions</span></header>
            <div className="emoji-grid">
              {QUICK_EMOJI.map((emoji) => (
                <button type="button" key={emoji} onClick={() => insertEmoji(emoji)} aria-label={`Insert ${emoji}`}>{emoji}</button>
              ))}
            </div>
          </div>
        )}
        {stickerPickerOpen && (
          <div className="sticker-picker">
            <header>
              <strong>Stickers</strong>
              <button type="button" className="icon-button" onClick={() => setStickerPickerOpen(false)} aria-label="Close sticker picker"><Icon name="close" /></button>
            </header>
            {stickerError && <p className="profile-form-error">{stickerError}</p>}
            {stickerPacks.length === 0 ? (
              <div className="sticker-picker__empty">
                <span>No sticker packs yet.</span>
                <button type="button" onClick={() => { setStickerPickerOpen(false); openStickerManager() }}>Manage packs</button>
              </div>
            ) : (
              stickerPacks.map((pack) => (
                <section className="sticker-picker__pack" key={pack.id}>
                  <h3>{pack.title}</h3>
                  <div className="sticker-grid">
                    {pack.stickers.map((sticker) => (
                      <button type="button" key={sticker.id} onClick={() => sendSticker(sticker)} title={sticker.emoji || 'Send sticker'}>
                        <AuthenticatedMedia path={sticker.image_url} token={token} alt="" className="sticker-image" />
                      </button>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
        )}
      </main>

      {dragActive && (
        <div className="drop-overlay" aria-hidden="true">
          <span><Icon name="attach" size={28} /></span>
          <strong>Drop to encrypt and send</strong>
          <small>AES-256-GCM · up to 50 MB</small>
        </div>
      )}

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
        <Modal title="Edit profile" onClose={closeProfile}>
          <form className="modal-form" onSubmit={saveProfile}>
            <label className="photo-picker">
              <Avatar name={profile.display_name || login} size={92} src={profileAvatarPreview || profile.avatar_url} />
              <span>{profileAvatar ? 'Choose another photo' : 'Upload a new photo'}</span>
              {profileAvatar && <small className="photo-picker__file">{profileAvatar.name}</small>}
              <input name="avatar" type="file" accept="image/jpeg,image/png,image/webp" onChange={selectProfileAvatar} />
            </label>
            <label>Public username
              <div className="username-field">
                <span>@</span>
                <input
                  value={profile.username || ''}
                  minLength={3}
                  maxLength={32}
                  pattern="[a-z0-9][a-z0-9_]{2,31}"
                  required
                  onChange={(event) => setProfile((value) => ({
                    ...value,
                    username: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''),
                  }))}
                />
              </div>
              <small className="field-hint">Unique and changeable. Your permanent account ID stays the same.</small>
            </label>
            <label>Display name<input value={profile.display_name || ''} maxLength={64} onChange={(event) => setProfile((value) => ({ ...value, display_name: event.target.value }))} /></label>
            <label>Bio<textarea value={profile.bio || ''} maxLength={160} rows={3} onChange={(event) => setProfile((value) => ({ ...value, bio: event.target.value }))} placeholder="A few words about you" /></label>
            <div className="profile-identity">
              <span>PERMANENT ID</span>
              <strong>#{profile.id || '—'}</strong>
              <small>Sign-in login: {login}</small>
            </div>
            {profileFormError && <p className="profile-form-error" role="alert">{profileFormError}</p>}
            <button className="primary-button" type="submit" disabled={profileSaving}>
              {profileSaving ? 'Saving…' : 'Save changes'}
            </button>
          </form>
        </Modal>
      )}

      {devicesOpen && (
        <Modal title="Trusted devices" onClose={() => setDevicesOpen(false)}>
          <div className="devices-panel">
            <header className="devices-panel__summary">
              <span>DEVICE TRUST</span>
              <strong>{devices.filter((device) => device.status !== 'revoked').length} / 5 slots used</strong>
              <p>Every active device has its own identity and MLS leaf.</p>
            </header>
            <div className="device-list">
              {devices.map((device) => (
                <article className={`device-row device-row--${device.status}`} key={device.id}>
                  <span className="device-glyph"><Icon name="shield" size={19} /></span>
                  <div>
                    <strong>{device.name}{device.current ? ' · This device' : ''}</strong>
                    <small>{device.status.toUpperCase()} · {device.fingerprint ? `FP ${device.fingerprint.slice(0, 12)}…` : 'Identity not published'}</small>
                    <small>History: {device.history_policy === 'new_only' ? 'new messages only' : 'encrypted transfer requested'}</small>
                  </div>
                  {device.status === 'active' ? (
                    <button type="button" className="danger-action" disabled={deviceBusy} onClick={() => revokeTrustedDevice(device)}>Revoke</button>
                  ) : <i>Revoked</i>}
                </article>
              ))}
            </div>
            <p className="devices-panel__notice">Revocation closes HTTP sessions and WebSockets immediately. Cryptographic removal completes only after clients apply the MLS Remove Commit.</p>
          </div>
        </Modal>
      )}

      {verification && (
        <Modal title={`Verify @${verification.contactLogin}`} onClose={() => setVerification(null)}>
          <div className="devices-panel">
            <p>Compare this QR code or all 60 digits over an authenticated channel. The code includes every active device credential verified against the current MLS tree.</p>
            <img src={verification.qr} width="240" height="240" alt="Contact safety QR code" />
            <code className="profile-identity">{verification.code}</code>
            <p className="devices-panel__notice">The code changes when either participant adds, replaces, or revokes an identity.</p>
          </div>
        </Modal>
      )}

      {stickerManagerOpen && (
        <Modal title="Sticker studio" onClose={() => setStickerManagerOpen(false)}>
          <div className="sticker-manager">
            {stickerError && <p className="profile-form-error" role="alert">{stickerError}</p>}
            <section className="sticker-manager__section">
              <div className="section-heading">
                <div>
                  <h3>Create a pack</h3>
                  <p>Build a public pack or keep it private.</p>
                </div>
              </div>
              <form className="pack-create-form" onSubmit={createStickerPack}>
                <input
                  value={packDraft.title}
                  maxLength={64}
                  placeholder="Pack title"
                  required
                  onChange={(event) => {
                    const title = event.target.value
                    setPackDraft((value) => ({
                      ...value,
                      title,
                      slug: value.slug || title.toLowerCase()
                        .replace(/[^a-z0-9]+/g, '-')
                        .replace(/^-|-$/g, ''),
                    }))
                  }}
                />
                <input
                  value={packDraft.slug}
                  minLength={2}
                  maxLength={64}
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  placeholder="pack-slug"
                  required
                  onChange={(event) => setPackDraft((value) => ({ ...value, slug: event.target.value.toLowerCase() }))}
                />
                <select value={packDraft.visibility} onChange={(event) => setPackDraft((value) => ({ ...value, visibility: event.target.value }))}>
                  <option value="private">Private</option>
                  <option value="public">Public</option>
                </select>
                <button className="primary-button" type="submit" disabled={stickerBusy}>Create pack</button>
              </form>
            </section>

            <section className="sticker-manager__section">
              <div className="section-heading">
                <div>
                  <h3>Add a sticker</h3>
                  <p>PNG or WebP, up to 5 MB. Crop and scale before upload.</p>
                </div>
              </div>
              {ownedPacks.length === 0 ? (
                <p className="section-empty">Create your first pack above.</p>
              ) : (
                <>
                  <div className="owned-pack-list">
                    {ownedPacks.map((pack) => (
                      <article className={selectedPackId === pack.id ? 'active' : ''} key={pack.id}>
                        <button type="button" className="owned-pack-select" onClick={() => setSelectedPackId(pack.id)}>
                          <span>{pack.title}<small>{pack.stickers.length} stickers</small></span>
                        </button>
                        <button type="button" className="visibility-toggle" onClick={() => toggleStickerPackVisibility(pack)}>
                          {pack.visibility}
                        </button>
                      </article>
                    ))}
                  </div>
                  <form className="sticker-upload-form" onSubmit={uploadSticker}>
                    <label className="sticker-cropper">
                      <span className="sticker-cropper__viewport">
                        {stickerPreview
                          ? <img src={stickerPreview} alt="Sticker crop preview" style={{ transform: `scale(${stickerZoom})` }} />
                          : <span>Choose PNG or WebP</span>}
                      </span>
                      <input type="file" accept="image/png,image/webp" onChange={selectStickerFile} />
                    </label>
                    {stickerFile && (
                      <label className="zoom-control">
                        Scale
                        <input type="range" min="1" max="2.5" step="0.05" value={stickerZoom} onChange={(event) => setStickerZoom(Number(event.target.value))} />
                      </label>
                    )}
                    <button className="primary-button" type="submit" disabled={!stickerFile || stickerBusy}>
                      {stickerBusy ? 'Processing…' : 'Add sticker'}
                    </button>
                  </form>
                </>
              )}
            </section>

            <section className="sticker-manager__section">
              <div className="section-heading">
                <div>
                  <h3>Discover public packs</h3>
                  <p>Add community packs to your library.</p>
                </div>
              </div>
              <div className="pack-list">
                {discoverPacks.map((pack) => (
                  <article className="pack-card" key={pack.id}>
                    <div>
                      <strong>{pack.title}</strong>
                      <span>@{pack.owner} · {pack.stickers.length} stickers</span>
                    </div>
                    {pack.editable ? (
                      <span className="pack-state">Yours</span>
                    ) : pack.subscribed ? (
                      <button type="button" className="pack-remove" onClick={() => unsubscribeFromStickerPack(pack.id)}>Remove</button>
                    ) : (
                      <button type="button" onClick={() => subscribeToStickerPack(pack.id)}>Add</button>
                    )}
                  </article>
                ))}
                {discoverPacks.length === 0 && <p className="section-empty">No public packs yet.</p>}
              </div>
            </section>
          </div>
        </Modal>
      )}

      {memberDialog && (
        <Modal title={memberDialog === 'owner' ? 'Transfer ownership' : `${memberDialog[0].toUpperCase()}${memberDialog.slice(1)} member`} onClose={() => setMemberDialog(null)}>
          <form className="modal-form member-picker" onSubmit={(event) => {
            event.preventDefault()
            if (memberDialog === 'owner') transferOwnership(memberLogin)
            else groupMemberAction(memberDialog, memberLogin)
          }}>
            <div className="member-picker__intro">
              <span>{['invite', 'add'].includes(memberDialog) ? 'TRUST DIRECTORY' : 'CURRENT MEMBERS'}</span>
              <strong>
                {['invite', 'add'].includes(memberDialog)
                  ? 'People you already know'
                  : 'Choose a group member'}
              </strong>
              <p>
                {['invite', 'add'].includes(memberDialog)
                  ? 'Only people from your existing private conversations are shown.'
                  : 'The permanent account identity is used for this action.'}
              </p>
            </div>
            <div className="member-picker__list" role="listbox" aria-label="Choose a person">
              {memberCandidates.map((person) => {
                const selected = memberLogin === person.login
                return (
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`member-choice ${selected ? 'is-selected' : ''}`}
                    key={person.login}
                    onClick={() => setMemberLogin(person.login)}
                  >
                    <Avatar name={person.display_name || person.username} size={44} src={person.avatar_url} />
                    <span>
                      <strong>{person.display_name || person.username}</strong>
                      <small>@{person.username}{person.id ? ` · ID #${person.id}` : ''}</small>
                    </span>
                    <i>{selected ? '✓ Selected' : 'Choose'}</i>
                  </button>
                )
              })}
              {memberCandidates.length === 0 && (
                <div className="member-picker__empty">
                  <Icon name="shield" />
                  <strong>No eligible people yet</strong>
                  <span>Start a private conversation first, then return here.</span>
                </div>
              )}
            </div>
            <label className="member-picker__manual">Or enter the sign-in login
              <input value={memberLogin} onChange={(event) => setMemberLogin(event.target.value)} placeholder="Exact login" />
            </label>
            <button className="primary-button" type="submit" disabled={!memberLogin.trim() || memberBusy}>
              {memberBusy ? 'Updating…' : 'Continue'}
            </button>
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
