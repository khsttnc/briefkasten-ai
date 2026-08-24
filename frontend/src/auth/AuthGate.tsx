import { FormEvent, ReactNode, useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from '../supabaseClient';

type AuthMode = 'password' | 'magiclink';
type PasswordAction = 'signin' | 'signup';

interface AuthGateProps {
  children: ReactNode;
}

function AuthGate({ children }: AuthGateProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [mode, setMode] = useState<AuthMode>('password');
  const [passwordAction, setPasswordAction] = useState<PasswordAction>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setInitializing(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setStatusMessage('');
    setSubmitting(true);

    try {
      if (mode === 'magiclink') {
        const { error: signInError } = await supabase.auth.signInWithOtp({ email });
        if (signInError) throw signInError;
        setStatusMessage('Giriş linki e-posta adresinize gönderildi. Gelen kutunuzu kontrol edin.');
      } else if (passwordAction === 'signup') {
        const { error: signUpError } = await supabase.auth.signUp({ email, password });
        if (signUpError) throw signUpError;
        setStatusMessage('Hesap oluşturuldu. E-postanızı onayladıktan sonra giriş yapabilirsiniz.');
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
        if (signInError) throw signInError;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Giriş sırasında bir hata oluştu.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSignOut = () => {
    supabase.auth.signOut();
  };

  if (initializing) {
    return (
      <section className="card">
        <div className="status-banner">Oturum kontrol ediliyor...</div>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="card">
        <div className="card-header">
          <h2>Devam etmek için giriş yapın</h2>
          <p>Belgelerinizi yükleyip analiz edebilmek için önce hesabınıza giriş yapmalısınız.</p>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab${mode === 'password' ? ' is-active' : ''}`}
            onClick={() => setMode('password')}
          >
            Şifre ile
          </button>
          <button
            type="button"
            className={`auth-tab${mode === 'magiclink' ? ' is-active' : ''}`}
            onClick={() => setMode('magiclink')}
          >
            Magic Link ile
          </button>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <label className="auth-field">
            <span>E-posta</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="auth-input"
              required
            />
          </label>

          {mode === 'password' && (
            <label className="auth-field">
              <span>Şifre</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="auth-input"
                required
                minLength={6}
              />
            </label>
          )}

          <div className="form-row">
            <button type="submit" className="primary-button" disabled={submitting}>
              {submitting
                ? 'Gönderiliyor...'
                : mode === 'magiclink'
                ? 'Giriş linki gönder'
                : passwordAction === 'signup'
                ? 'Kayıt ol'
                : 'Giriş yap'}
            </button>

            {mode === 'password' && (
              <button
                type="button"
                className="secondary-button"
                onClick={() => setPasswordAction(passwordAction === 'signin' ? 'signup' : 'signin')}
              >
                {passwordAction === 'signin'
                  ? 'Hesabınız yok mu? Kayıt olun'
                  : 'Zaten hesabınız var mı? Giriş yapın'}
              </button>
            )}
          </div>

          {statusMessage && <div className="status-banner">{statusMessage}</div>}
          {error && <div className="error-banner">{error}</div>}
        </form>
      </section>
    );
  }

  return (
    <>
      <div className="auth-status-bar">
        <span className="muted-text">{session.user.email}</span>
        <button type="button" className="secondary-button" onClick={handleSignOut}>
          Çıkış yap
        </button>
      </div>
      {children}
    </>
  );
}

export default AuthGate;
