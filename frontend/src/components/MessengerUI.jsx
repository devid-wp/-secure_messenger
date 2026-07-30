const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const AVATAR_GRADIENTS = [
  ['#7c5cff', '#4d35b8'],
  ['#f2a84b', '#bd6428'],
  ['#3ebf91', '#247a68'],
  ['#cf6f8f', '#85425f'],
  ['#5f9de8', '#385e9f'],
]

function avatarGradient(name) {
  let hash = 0
  for (let index = 0; index < name.length; index += 1) {
    hash = name.charCodeAt(index) + ((hash << 5) - hash)
  }
  return AVATAR_GRADIENTS[Math.abs(hash) % AVATAR_GRADIENTS.length]
}

function memberCountLabel(count) {
  return `${count} ${count === 1 ? 'member' : 'members'}`
}

export function Icon({ name, size = 18 }) {
  const paths = {
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    compose: <path d="M13.5 5.5 18.5 10.5M5 19l3.8-.8L19 7a2.1 2.1 0 0 0-3-3L4.8 14.2 4 18z" />,
    search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    more: <><circle cx="12" cy="5" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="19" r="1" fill="currentColor" stroke="none" /></>,
    back: <path d="m15 18-6-6 6-6" />,
    send: <path d="m4 4 17 8-17 8 3-8-3-8Zm3 8h14" />,
    attach: <path d="m9 17 7.6-7.6a3.5 3.5 0 0 0-5-5L4.8 11.2a5 5 0 0 0 7 7l6.4-6.4" />,
    sticker: <><path d="M5 4h14a1 1 0 0 1 1 1v9l-6 6H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" /><path d="M14 20v-5a1 1 0 0 1 1-1h5M8 9h.01M16 9h.01M8.5 13c2 1.7 5 1.7 7 0" /></>,
    emoji: <><circle cx="12" cy="12" r="9" /><path d="M8 14c1.8 2 6.2 2 8 0M9 9h.01M15 9h.01" /></>,
    reply: <path d="m10 8-5 4 5 4v-3h4c3 0 5 1 6 4 0-6-3-8-10-8V8Z" />,
    edit: <path d="m13.5 5.5 5 5M5 19l3.8-.8L19 7a2.1 2.1 0 0 0-3-3L4.8 14.2 4 18z" />,
    trash: <><path d="M5 7h14M9 7V4h6v3M8 10v8m4-8v8m4-8v8M7 7l1 14h8l1-14" /></>,
    shield: <path d="M12 3 5 6v5c0 4.5 2.7 8 7 10 4.3-2 7-5.5 7-10V6l-7-3Z" />,
  }
  return (
    <svg aria-hidden="true" className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  )
}

export function Avatar({ name, size = 40, src = null, online = false }) {
  const safeName = name || '?'
  const imageSource = src?.startsWith('/') ? `${API_URL}${src}` : src
  const [start, end] = avatarGradient(safeName)
  /** @type {import('react').CSSProperties & Record<string, string | number>} */
  const avatarStyle = {
    '--avatar-size': `${size}px`,
    '--avatar-start': start,
    '--avatar-end': end,
    fontSize: size * 0.39,
  }
  return (
    <span
      className={`avatar ${imageSource ? 'avatar--image' : ''}`}
      style={avatarStyle}
      aria-hidden="true"
    >
      {imageSource ? <img src={imageSource} alt="" /> : safeName.charAt(0).toUpperCase()}
      {online && <span className="avatar-status" />}
    </span>
  )
}

export function SearchInput({ value, onChange, loading = false }) {
  return (
    <div className="search-control">
      <Icon name="search" size={17} />
      <input
        type="search"
        value={value}
        onChange={onChange}
        placeholder="Search @username or name"
        aria-label="Search users"
      />
      {loading && <span className="search-spinner" aria-label="Searching" />}
      {value && (
        <button type="button" className="search-clear" onClick={() => onChange({ target: { value: '' } })} aria-label="Clear search">
          <Icon name="close" size={15} />
        </button>
      )}
    </div>
  )
}

function previewMessage(lastMessage) {
  if (!lastMessage) return ''
  if (lastMessage.kind === 'sticker') return 'Sticker'
  if (lastMessage.kind === 'image') return 'Photo'
  if (lastMessage.kind === 'file') return 'File'
  return lastMessage.content
}

function previewTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function ContactListItem({ conversation, active, onSelect }) {
  const subtitle = conversation.isSearchResult
    ? `@${conversation.username} · ID #${conversation.stableUserId}`
    : previewMessage(conversation.lastMessage)
      || (conversation.type === 'group'
        ? memberCountLabel(conversation.memberCount)
        : 'Private conversation')
  return (
    <button
      type="button"
      className={`contact-item ${active ? 'active' : ''}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return
        event.preventDefault()
        const items = [...event.currentTarget.parentElement.querySelectorAll('.contact-item')]
        const current = items.indexOf(event.currentTarget)
        const offset = event.key === 'ArrowDown' ? 1 : -1
        const target = items[(current + offset + items.length) % items.length]
        if (target instanceof HTMLElement) target.focus()
      }}
      aria-current={active ? 'page' : undefined}
    >
      <Avatar name={conversation.label} size={46} src={conversation.avatarUrl} />
      <span className="contact-copy">
        <span className="contact-name-row">
          <span className="contact-name">{conversation.label}</span>
          <time>{previewTime(conversation.lastMessage?.timestamp)}</time>
        </span>
        <span className="contact-preview">{subtitle}</span>
      </span>
      {conversation.unreadCount > 0
        ? <span className="unread-badge" aria-label={`${conversation.unreadCount} unread messages`}>{Math.min(conversation.unreadCount, 99)}</span>
        : <span className="contact-kind">{conversation.type === 'group' ? 'GROUP' : 'DM'}</span>}
    </button>
  )
}

export function ConnectionStatus({ connected }) {
  return (
    <span className={`connection-chip ${connected ? 'is-connected' : 'is-connecting'}`} role="status" aria-live="polite">
      <span className="connection-chip__mark" />
      {connected ? 'CONNECTED' : 'RECONNECTING'}
    </span>
  )
}

export function ChatHeader({ conversation, connected, onBack, onMenu }) {
  const conversationDetails = conversation?.type === 'group'
    ? `${memberCountLabel(conversation.memberCount)} · ${connected ? 'online' : 'reconnecting'}`
    : conversation?.username
      ? `@${conversation.username} · ID #${conversation.stableUserId}`
      : 'Private conversation'

  return (
    <header className="chat-header">
      <button type="button" className="mobile-back icon-button" onClick={onBack} aria-label="Back to conversations">
        <Icon name="back" />
      </button>
      <div className="chat-header__identity">
        {conversation ? <Avatar name={conversation.label} size={42} src={conversation.avatarUrl} /> : <span className="brand-mark brand-mark--small"><Icon name="shield" /></span>}
        <span className="chat-header__copy">
          <strong>{conversation?.label || 'Secure Messenger'}</strong>
          <span>{conversation ? conversationDetails : 'Select a conversation to begin'}</span>
        </span>
      </div>
      <div className="chat-header__controls">
        <ConnectionStatus connected={connected} />
        {conversation && (
          <button type="button" className="icon-button" onClick={onMenu} aria-label="Conversation menu">
            <Icon name="more" />
          </button>
        )}
      </div>
    </header>
  )
}

const STATUS_META = {
  sending: { symbol: '◷', label: 'Sending' },
  sent: { symbol: '✓', label: 'Sent' },
  delivered: { symbol: '✓✓', label: 'Delivered' },
  read: { symbol: '✓✓', label: 'Read' },
  failed: { symbol: '!', label: 'Failed. It will retry when connected.' },
}

export function MessageStatus({ status }) {
  const meta = STATUS_META[status]
  if (!meta) return null
  return <span className={`message-status message-status--${status}`} title={meta.label} aria-label={meta.label}>{meta.symbol}</span>
}

export function MessageActions({ message, own, onReply, onEdit, onDelete }) {
  return (
    <div className="message-actions" role="group" aria-label="Message actions">
      <button type="button" onClick={() => onReply(message)} title="Reply" aria-label="Reply"><Icon name="reply" size={16} /></button>
      {own && (
        <>
          {message.kind === 'text' && <button type="button" onClick={() => onEdit(message)} title="Edit" aria-label="Edit"><Icon name="edit" size={15} /></button>}
          <button type="button" onClick={() => onDelete(message)} title="Delete" aria-label="Delete"><Icon name="trash" size={15} /></button>
        </>
      )}
    </div>
  )
}

export function EmptyState({ conversation }) {
  const hasConversation = Boolean(conversation)
  return (
    <div className="empty-state">
      <span className="empty-state__mark"><Icon name="shield" size={28} /></span>
      <h2>{hasConversation ? 'No messages yet' : 'Secure Messenger'}</h2>
      <p>
        {hasConversation
          ? conversation.type === 'group'
            ? `Start the conversation in ${conversation.label}.`
            : `Start a private conversation with ${conversation.label}.`
          : 'Select a conversation to begin.'}
      </p>
    </div>
  )
}

export function MessageComposer({ inputRef, value, onChange, onSubmit, onSticker, onEmoji, onAttach, conversation, disabled }) {
  const handleChange = (event) => {
    event.target.style.height = 'auto'
    event.target.style.height = `${Math.min(event.target.scrollHeight, 120)}px`
    onChange(event)
  }
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit(event)
    }
  }
  return (
    <form className={`message-composer ${value.trim() ? 'has-content' : ''}`} onSubmit={onSubmit}>
      <button type="button" className="icon-button composer-attach" onClick={onAttach} title="Attach an encrypted file" aria-label="Attach file">
        <Icon name="attach" />
      </button>
      <button type="button" className="icon-button composer-emoji" disabled={disabled} onClick={onEmoji} title="Emoji" aria-label="Open emoji picker">
        <Icon name="emoji" />
      </button>
      <button
        type="button"
        className="icon-button composer-sticker"
        disabled={disabled}
        onClick={onSticker}
        title="Send a sticker"
        aria-label="Open sticker picker"
      >
        <Icon name="sticker" />
      </button>
      <div className="composer-input">
        <textarea
          ref={inputRef}
          rows={1}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={conversation ? `Message ${conversation.label}` : 'Select a conversation first'}
          aria-label="Message"
        />
      </div>
      <button
        type="submit"
        className="send-button"
        disabled={disabled || !value.trim()}
        title={value.trim() ? 'Send message' : 'Write a message to send'}
        aria-label="Send message"
      >
        <Icon name="send" />
      </button>
    </form>
  )
}

export function Modal({ title, children, onClose }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose} onKeyDown={(event) => event.key === 'Escape' && onClose()}>
      <section className="modal-card" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()} tabIndex={-1} autoFocus>
        <header className="modal-card__header">
          <h2>{title}</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </header>
        {children}
      </section>
    </div>
  )
}

export function ConversationSkeleton() {
  return (
    <div className="conversation-skeleton" aria-label="Loading conversations" aria-busy="true">
      {[0, 1, 2, 3, 4].map((item) => (
        <div className="skeleton-row" key={item}>
          <span className="skeleton-avatar" />
          <span className="skeleton-copy"><i /><i /></span>
        </div>
      ))}
    </div>
  )
}

export function MessagesSkeleton() {
  return (
    <div className="messages-skeleton" aria-label="Loading messages" aria-busy="true">
      <span /><span /><span /><span />
    </div>
  )
}

export function MobileNavigation({ unreadCount, onNewGroup, onProfile }) {
  return (
    <nav className="mobile-navigation" aria-label="Mobile navigation">
      <span className="mobile-navigation__active">
        <Icon name="shield" size={18} />
        Chats
        {unreadCount > 0 && <i>{Math.min(unreadCount, 99)}</i>}
      </span>
      <button type="button" onClick={onNewGroup}>
        <Icon name="compose" size={18} />
        New group
      </button>
      <button type="button" onClick={onProfile}>
        <Icon name="more" size={18} />
        Profile
      </button>
    </nav>
  )
}
