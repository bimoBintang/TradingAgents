import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children?: ReactNode;
}

interface StackFrame {
  fn: string;
  file: string;
  line: string;
  col: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Parse a JS stack trace string into structured frames.
 * Handles Chrome/V8 ("at Foo (file:line:col)") and Firefox/Safari ("Foo@file:line:col").
 */
function parseStackFrames(stack: string | undefined): StackFrame[] {
  if (!stack) return [];
  const frames: StackFrame[] = [];

  for (const rawLine of stack.split('\n')) {
    const line = rawLine.trim();

    // Chrome/V8: "at ComponentName (http://localhost:5173/src/components/Foo.tsx:42:5)"
    const chromeMatch = line.match(
      /at\s+(.+?)\s+\((.+?):(\d+):(\d+)\)/
    );
    if (chromeMatch) {
      frames.push({ fn: chromeMatch[1], file: chromeMatch[2], line: chromeMatch[3], col: chromeMatch[4] });
      continue;
    }

    // Chrome/V8 anonymous: "at http://localhost:5173/src/main.tsx:8:3"
    const chromeAnon = line.match(
      /at\s+(.+?):(\d+):(\d+)/
    );
    if (chromeAnon) {
      frames.push({ fn: '(anonymous)', file: chromeAnon[1], line: chromeAnon[2], col: chromeAnon[3] });
      continue;
    }

    // Firefox/Safari: "render@http://localhost:5173/src/components/Foo.tsx:42:5"
    const firefoxMatch = line.match(
      /(.+?)@(.+?):(\d+):(\d+)/
    );
    if (firefoxMatch) {
      frames.push({ fn: firefoxMatch[1] || '(anonymous)', file: firefoxMatch[2], line: firefoxMatch[3], col: firefoxMatch[4] });
    }
  }

  return frames;
}

/** Extract a short filename from a full URL path, e.g. "src/components/Foo.tsx" */
function shortPath(fullPath: string): string {
  try {
    const url = new URL(fullPath);
    // Remove origin, keep path from /src/
    const srcIdx = url.pathname.indexOf('/src/');
    return srcIdx !== -1 ? url.pathname.slice(srcIdx + 1) : url.pathname;
  } catch {
    // Not a URL, try to extract from path
    const srcIdx = fullPath.indexOf('/src/');
    return srcIdx !== -1 ? fullPath.slice(srcIdx + 1) : fullPath;
  }
}

/** Parse React componentStack (from ErrorInfo) into component names */
function parseComponentStack(componentStack: string | undefined): string[] {
  if (!componentStack) return [];
  return componentStack
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.startsWith('at '))
    .map(l => {
      // "at ChartPanel (http://localhost:5173/src/components/dashboard/ChartPanel.tsx:115:25)"
      const match = l.match(/at\s+(\S+)/);
      return match ? match[1] : l;
    });
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  public render() {
    if (!this.state.hasError) return this.props.children;

    const { error, errorInfo } = this.state;
    const frames = parseStackFrames(error?.stack);
    const componentChain = parseComponentStack(errorInfo?.componentStack as string | undefined);

    // Find the most relevant "user code" frame (first one from /src/)
    const userFrame = frames.find(f => f.file.includes('/src/'));

    return (
      <div style={{
        minHeight: '100vh', width: '100vw', padding: '2rem',
        background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)',
        color: '#e2e8f0', fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
      }}>
        {/* Header */}
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 12, background: '#ef4444',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, fontWeight: 'bold',
            }}>✕</div>
            <div>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#f87171' }}>
                Runtime Error
              </h1>
              <p style={{ margin: 0, fontSize: 13, color: '#94a3b8' }}>
                An unhandled error crashed this component tree
              </p>
            </div>
          </div>

          {/* Error Message */}
          <div style={{
            background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: 12, padding: '16px 20px', marginBottom: 20,
          }}>
            <div style={{ fontSize: 11, color: '#f87171', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
              {error?.name || 'Error'}
            </div>
            <div style={{ fontSize: 15, fontWeight: 500, color: '#fca5a5', lineHeight: 1.5 }}>
              {error?.message || 'Unknown error'}
            </div>
          </div>

          {/* Pinpointed Location */}
          {userFrame && (
            <div style={{
              background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: 12, padding: '16px 20px', marginBottom: 20,
            }}>
              <div style={{ fontSize: 11, color: '#60a5fa', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                📍 Error Location
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <code style={{
                  background: 'rgba(0,0,0,0.3)', padding: '6px 12px', borderRadius: 8,
                  fontSize: 14, color: '#93c5fd', fontFamily: "'Fira Code', 'JetBrains Mono', monospace",
                }}>
                  {shortPath(userFrame.file)}
                </code>
                <span style={{
                  background: '#2563eb', color: 'white', padding: '4px 10px',
                  borderRadius: 6, fontSize: 12, fontWeight: 700,
                }}>
                  Line {userFrame.line}:{userFrame.col}
                </span>
                <span style={{ color: '#cbd5e1', fontSize: 13 }}>
                  in <strong style={{ color: '#a5b4fc' }}>{userFrame.fn}</strong>
                </span>
              </div>
            </div>
          )}

          {/* Component Tree */}
          {componentChain.length > 0 && (
            <div style={{
              background: 'rgba(139, 92, 246, 0.08)', border: '1px solid rgba(139, 92, 246, 0.25)',
              borderRadius: 12, padding: '16px 20px', marginBottom: 20,
            }}>
              <div style={{ fontSize: 11, color: '#a78bfa', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                🧩 React Component Tree
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                {componentChain.map((name, i) => (
                  <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <code style={{
                      background: i === 0 ? 'rgba(239, 68, 68, 0.2)' : 'rgba(0,0,0,0.2)',
                      border: i === 0 ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(255,255,255,0.06)',
                      color: i === 0 ? '#fca5a5' : '#c4b5fd',
                      padding: '3px 8px', borderRadius: 6, fontSize: 12,
                      fontFamily: "'Fira Code', monospace",
                    }}>
                      {name}
                    </code>
                    {i < componentChain.length - 1 && <span style={{ color: '#475569' }}>→</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Full Stack Trace */}
          {frames.length > 0 && (
            <details style={{ marginBottom: 20 }}>
              <summary style={{
                cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#94a3b8',
                padding: '10px 0', userSelect: 'none',
              }}>
                🔍 Full Stack Trace ({frames.length} frames)
              </summary>
              <div style={{
                background: 'rgba(0,0,0,0.3)', borderRadius: 12, overflow: 'hidden',
                border: '1px solid rgba(255,255,255,0.06)',
              }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: 'rgba(0,0,0,0.3)' }}>
                      <th style={{ ...thStyle, width: 32 }}>#</th>
                      <th style={{ ...thStyle, textAlign: 'left' }}>Function</th>
                      <th style={{ ...thStyle, textAlign: 'left' }}>File</th>
                      <th style={{ ...thStyle, width: 80 }}>Line:Col</th>
                    </tr>
                  </thead>
                  <tbody>
                    {frames.map((f, i) => {
                      const isUserCode = f.file.includes('/src/');
                      return (
                        <tr key={i} style={{
                          background: isUserCode ? 'rgba(59, 130, 246, 0.06)' : 'transparent',
                          borderBottom: '1px solid rgba(255,255,255,0.04)',
                        }}>
                          <td style={{ ...tdStyle, color: '#64748b', textAlign: 'center' }}>{i + 1}</td>
                          <td style={{ ...tdStyle, color: isUserCode ? '#93c5fd' : '#64748b', fontFamily: "'Fira Code', monospace" }}>
                            {f.fn}
                          </td>
                          <td style={{ ...tdStyle, color: isUserCode ? '#a5b4fc' : '#475569', fontFamily: "'Fira Code', monospace", fontSize: 11 }}>
                            {shortPath(f.file)}
                          </td>
                          <td style={{ ...tdStyle, color: isUserCode ? '#fbbf24' : '#64748b', textAlign: 'center', fontWeight: isUserCode ? 600 : 400 }}>
                            {f.line}:{f.col}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          )}

          {/* Raw Error (fallback) */}
          <details style={{ marginBottom: 20 }}>
            <summary style={{
              cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#94a3b8',
              padding: '10px 0', userSelect: 'none',
            }}>
              📄 Raw Error Output
            </summary>
            <pre style={{
              background: 'rgba(0,0,0,0.4)', padding: 16, borderRadius: 12,
              fontSize: 11, color: '#94a3b8', overflowX: 'auto', whiteSpace: 'pre-wrap',
              border: '1px solid rgba(255,255,255,0.06)',
              fontFamily: "'Fira Code', 'JetBrains Mono', monospace",
            }}>
              {error?.stack || error?.toString() || 'No error details available'}
            </pre>
          </details>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: '#3b82f6', color: 'white', border: 'none', borderRadius: 10,
                padding: '12px 28px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = '#2563eb')}
              onMouseOut={(e) => (e.currentTarget.style.background = '#3b82f6')}
            >
              🔄 Reload Page
            </button>
            <button
              onClick={() => {
                const text = [
                  `Error: ${error?.message}`,
                  userFrame ? `File: ${shortPath(userFrame.file)}:${userFrame.line}:${userFrame.col}` : '',
                  userFrame ? `Function: ${userFrame.fn}` : '',
                  `\nStack:\n${error?.stack}`,
                ].filter(Boolean).join('\n');
                navigator.clipboard.writeText(text);
              }}
              style={{
                background: 'rgba(255,255,255,0.08)', color: '#cbd5e1', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 10, padding: '12px 28px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.12)')}
              onMouseOut={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.08)')}
            >
              📋 Copy Error
            </button>
          </div>
        </div>
      </div>
    );
  }
}

// Inline styles for table cells
const thStyle: React.CSSProperties = {
  padding: '8px 12px', color: '#64748b', fontSize: 10,
  fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1,
};
const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
};
