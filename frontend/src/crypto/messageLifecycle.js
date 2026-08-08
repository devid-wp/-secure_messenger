export function applyMessageLifecycle(events) {
  const messages = []
  const byClientId = new Map()
  const seenEvents = new Set()
  const pending = []

  for (const event of events) {
    const item = event.item
    if (!item || seenEvents.has(item.client_id)) continue
    seenEvents.add(item.client_id)
    if (item.type === 'message' || item.type === 'attachment' || item.type === 'device_event') {
      const message = { ...item, ...event.envelope }
      if (item.type === 'device_event') Object.assign(message, { kind: 'system', content: item.event })
      messages.push(message)
      byClientId.set(item.client_id, message)
    } else if (item.type !== 'group_metadata') pending.push(event)
  }

  for (const { item, envelope } of pending) {
    const target = byClientId.get(item.target_client_id)
    if (!target) continue
    const sameAuthor = item.sender && target.sender
      ? target.sender === item.sender
      : target.sender_device_id === item.sender_device_id
    if (item.type === 'edit' && sameAuthor && !target.deleted_at) Object.assign(target, { content: item.content, edited_at: envelope.timestamp })
    else if (item.type === 'delete' && sameAuthor) Object.assign(target, { content: '', deleted_at: envelope.timestamp })
    else if (item.type === 'reaction') {
      const reactions = new Map((target.reactions || []).map((reaction) => [`${reaction.sender_device_id}:${reaction.emoji}`, reaction]))
      reactions.set(`${item.sender_device_id}:${item.emoji}`, { sender: item.sender, sender_device_id: item.sender_device_id, emoji: item.emoji })
      target.reactions = [...reactions.values()]
    } else if (item.type === 'receipt') {
      const receipts = { ...(target.receipts || {}) }
      receipts[item.sender_device_id] = item.state
      target.receipts = receipts
    }
  }

  for (const message of messages) {
    const targetId = message.reply?.target_client_id
    if (!targetId) continue
    const target = byClientId.get(targetId)
    message.reply_to_client_id = targetId
    message.reply_to_sender = target?.sender || null
    message.reply_to_content = target?.deleted_at ? '' : target?.content || null
  }
  return messages
}
