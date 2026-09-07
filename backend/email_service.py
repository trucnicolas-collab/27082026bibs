"""Service d'envoi d'emails transactionnels via Resend.

Envois pris en charge :
- Réinitialisation de mot de passe (lien avec token, valable 1h)
- Notification d'un mot de passe réinitialisé par un admin (nouveau MDP à usage unique)

Configuration (.env) :
- RESEND_API_KEY : clé API Resend (obtenue sur https://resend.com/api-keys)
- SENDER_EMAIL  : adresse d'envoi (défaut : `onboarding@resend.dev` pour tests,
                  puis `phasage@vusion.com` en prod après vérification du domaine)
- FRONTEND_URL  : URL publique du front (utilisée dans les liens des emails)

Les erreurs d'envoi ne remontent JAMAIS aux endpoints appelants : elles sont
loguées en WARNING, l'appelant peut continuer (le comportement historique
d'affichage du lien dans les logs reste actif en fallback).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _get_client():
    """Charge la clé Resend à chaque appel (permet la mise à jour à chaud)."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import resend
    except ImportError:
        logger.warning("Package 'resend' non installé — envoi email désactivé.")
        return None
    resend.api_key = api_key
    return resend


def is_configured() -> bool:
    """True si Resend est configuré et prêt à envoyer."""
    return bool(os.environ.get("RESEND_API_KEY", "").strip())


async def _send(to: str, subject: str, html: str, text: str) -> Optional[str]:
    """Envoie un email. Renvoie l'ID Resend en cas de succès, None sinon."""
    resend_mod = _get_client()
    if resend_mod is None:
        logger.info(f"[EMAIL DÉSACTIVÉ] Aurait envoyé à {to} : {subject}")
        return None
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev").strip()
    params = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    try:
        # Resend SDK est synchrone → thread pour ne pas bloquer l'event loop
        result = await asyncio.to_thread(resend_mod.Emails.send, params)
        email_id = result.get("id") if isinstance(result, dict) else None
        logger.info(f"Email envoyé à {to} (id={email_id}) : {subject}")
        return email_id
    except Exception as e:
        logger.warning(f"Échec envoi email à {to} : {e}")
        return None


# ── Templates HTML minimalistes (inline CSS pour compat clients mail) ────────

def _wrap_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;padding:0;background:#F5F6F8;font-family:Arial,sans-serif;color:#1F2937;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F5F6F8;padding:32px 12px;">
  <tr><td align="center">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:12px;overflow:hidden;max-width:100%;">
      <tr><td style="background:#005BAB;padding:20px 32px;color:#FFFFFF;font-size:18px;font-weight:600;">
        Phasage & suivi de déploiement
      </td></tr>
      <tr><td style="padding:28px 32px 24px 32px;font-size:14px;line-height:1.6;">
        {body}
      </td></tr>
      <tr><td style="padding:14px 32px 22px 32px;font-size:12px;color:#6B7280;border-top:1px solid #E5E7EB;">
        Email automatique — merci de ne pas répondre.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


async def send_password_reset_email(email: str, reset_link: str, user_name: str = "") -> bool:
    """Envoie le lien de réinitialisation de mot de passe (valable 1h)."""
    greeting = f"Bonjour {user_name}," if user_name else "Bonjour,"
    body = f"""
      <p>{greeting}</p>
      <p>Vous avez demandé la réinitialisation de votre mot de passe.
      Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe :</p>
      <p style="text-align:center;margin:24px 0;">
        <a href="{reset_link}" style="display:inline-block;background:#005BAB;color:#FFFFFF;
           padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;">
          Réinitialiser mon mot de passe
        </a>
      </p>
      <p style="font-size:12px;color:#6B7280;">
        Ce lien est valable <strong>1 heure</strong>. Passé ce délai, vous devrez refaire une demande.
      </p>
      <p style="font-size:12px;color:#6B7280;">
        Si le bouton ne fonctionne pas, copiez-collez ce lien :<br>
        <span style="word-break:break-all;">{reset_link}</span>
      </p>
      <p style="font-size:12px;color:#6B7280;margin-top:16px;">
        Vous n'êtes pas à l'origine de cette demande ? Ignorez simplement ce message.
      </p>
    """
    text = (
        f"{greeting}\n\n"
        f"Réinitialisez votre mot de passe (lien valable 1h) :\n{reset_link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
    )
    result = await _send(email, "Réinitialisation de votre mot de passe", _wrap_html("Réinitialisation", body), text)
    return result is not None


async def send_admin_password_reset_email(email: str, new_password: str, user_name: str = "") -> bool:
    """Envoie le nouveau mot de passe généré par un admin (usage unique, à changer)."""
    greeting = f"Bonjour {user_name}," if user_name else "Bonjour,"
    body = f"""
      <p>{greeting}</p>
      <p>Un administrateur vient de réinitialiser votre mot de passe.
      Voici votre nouveau mot de passe temporaire :</p>
      <p style="text-align:center;margin:24px 0;">
        <span style="display:inline-block;background:#F3F4F6;color:#111827;padding:14px 22px;
              border-radius:8px;font-family:'Courier New',monospace;font-size:16px;letter-spacing:1px;
              border:1px solid #E5E7EB;">{new_password}</span>
      </p>
      <p style="font-size:13px;">
        Connectez-vous avec ce mot de passe, puis <strong>changez-le immédiatement</strong>
        via "Mot de passe oublié ?" sur l'écran de connexion.
      </p>
    """
    text = (
        f"{greeting}\n\n"
        f"Votre nouveau mot de passe temporaire : {new_password}\n\n"
        "Merci de le changer dès votre première connexion."
    )
    result = await _send(email, "Nouveau mot de passe — Phasage", _wrap_html("Nouveau mot de passe", body), text)
    return result is not None
