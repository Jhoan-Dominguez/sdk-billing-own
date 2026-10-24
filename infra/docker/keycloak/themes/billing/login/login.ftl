<#--
  Inicio de sesión: correo + contraseña, "Crear cuenta" a la derecha del botón
  principal y Google debajo. El botón de Google funciona en cuanto exista el
  proveedor de identidad `google` en el realm (docker/keycloak/configure-google.sh);
  mientras no exista se muestra deshabilitado.
-->
<#import "template.ftl" as layout>
<#import "passkeys.ftl" as passkeys>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=false; section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "form">
        <p class="cp-subtitle">${msg("cpSubtitle")}</p>
        <#if realm.password>
            <form id="kc-form-login" class="cp-form" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
                <#if !usernameHidden??>
                    <div class="cp-field">
                        <label for="username" class="cp-label">${msg("email")}</label>
                        <input tabindex="1" id="username" class="cp-input" name="username" value="${(login.username!'')}"
                               type="email" inputmode="email" autofocus
                               autocomplete="${(enableWebAuthnConditionalUI?has_content)?then('username webauthn', 'username')}"
                               placeholder="tu@correo.com"
                               aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                               dir="ltr"/>
                    </div>
                </#if>

                <div class="cp-field">
                    <div class="cp-label-row">
                        <label for="password" class="cp-label">${msg("password")}</label>
                        <#if realm.resetPasswordAllowed>
                            <a tabindex="6" class="cp-link cp-small" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
                        </#if>
                    </div>
                    <div class="cp-input-group" dir="ltr">
                        <input tabindex="2" id="password" class="cp-input" name="password" type="password"
                               autocomplete="current-password"
                               aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"/>
                        <button class="cp-eye" type="button" aria-label="${msg("showPassword")}"
                                aria-controls="password" data-password-toggle tabindex="3"
                                data-icon-show="cp-icon cp-icon-eye" data-icon-hide="cp-icon cp-icon-eye-off"
                                data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                            <i class="cp-icon cp-icon-eye" aria-hidden="true"></i>
                        </button>
                    </div>
                    <#if messagesPerField.existsError('username','password')>
                        <span id="input-error" class="cp-error" aria-live="polite">
                            ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
                        </span>
                    </#if>
                </div>

                <#if realm.rememberMe && !usernameHidden??>
                    <label class="cp-check-row">
                        <input tabindex="4" id="rememberMe" name="rememberMe" type="checkbox" class="cp-check" <#if login.rememberMe??>checked</#if>>
                        <span class="cp-check-label">${msg("rememberMe")}</span>
                    </label>
                </#if>

                <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                <div class="cp-actions cp-actions-split">
                    <button tabindex="5" class="cp-btn cp-btn-primary" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
                    <#if realm.registrationAllowed && !registrationDisabled??>
                        <a tabindex="7" class="cp-btn cp-btn-secondary" id="kc-register" href="${url.registrationUrl}">${msg("doRegister")}</a>
                    </#if>
                </div>
            </form>
        </#if>
        <@passkeys.conditionalUIData />
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    <#elseif section = "socialProviders">
        <#if realm.password>
            <div id="kc-social-providers" class="cp-social-section">
                <div class="cp-divider"><span>${msg("identity-provider-login-label")}</span></div>
                <#assign google = (social.providers![])?filter(p -> p.alias == "google")>
                <#if google?has_content>
                    <a data-once-link data-disabled-class="cp-btn-disabled" id="social-google"
                       class="cp-btn cp-btn-social" href="${google[0].loginUrl}">
                        <#include "google-logo.ftl"> <span>${msg("cpGoogle")}</span>
                    </a>
                <#else>
                    <button type="button" class="cp-btn cp-btn-social" id="social-google" disabled
                            aria-describedby="google-soon">
                        <#include "google-logo.ftl"> <span>${msg("cpGoogle")}</span>
                    </button>
                    <p id="google-soon" class="cp-muted cp-small">${msg("cpGoogleSoon")}</p>
                </#if>
                <#list (social.providers![])?filter(p -> p.alias != "google") as p>
                    <a data-once-link data-disabled-class="cp-btn-disabled" id="social-${p.alias}"
                       class="cp-btn cp-btn-social" href="${p.loginUrl}"><span>${p.displayName!}</span></a>
                </#list>
            </div>
        </#if>
    </#if>
</@layout.registrationLayout>
