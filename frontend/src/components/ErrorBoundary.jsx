import React from 'react'

/**
 * Catches render-time errors in the chat tree and renders a fallback
 * instead of unmounting the whole app to a black screen. Render failures can
 * include message content in their text or component props, so neither the
 * error nor its stack is exposed to the user or browser console.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  handleReset = () => {
    this.setState({ hasError: false })
  }

  handleReload = () => {
    // Hard reload to recover from a stuck state.
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <div className="error-boundary-icon" aria-hidden="true">⚠️</div>
          <h2>Что-то пошло не так</h2>
          <p className="error-boundary-sub">
            Произошла ошибка рендера. Попробуйте перезагрузить страницу.
          </p>
          <div className="error-boundary-actions">
            <button type="button" className="error-boundary-btn" onClick={this.handleReset}>
              Попробовать снова
            </button>
            <button type="button" className="error-boundary-btn primary" onClick={this.handleReload}>
              Перезагрузить
            </button>
          </div>
        </div>
      </div>
    )
  }
}

export default ErrorBoundary
