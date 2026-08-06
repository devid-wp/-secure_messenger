import React from 'react'

/**
 * Catches render-time errors in the chat tree and renders a fallback
 * instead of unmounting the whole app to a black screen. Reports the
 * error to the console for debugging.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary] render failure:', error, info)
    this.setState({ info })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, info: null })
  }

  handleReload = () => {
    // Hard reload to recover from a stuck state.
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children
    const { error, info } = this.state
    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <div className="error-boundary-icon" aria-hidden="true">⚠️</div>
          <h2>Что-то пошло не так</h2>
          <p className="error-boundary-sub">
            Произошла ошибка рендера. Попробуйте перезагрузить страницу.
          </p>
          {error && (
            <pre className="error-boundary-stack">
              {String(error?.message || error)}
              {info?.componentStack ? '\n\n' + info.componentStack : ''}
            </pre>
          )}
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
