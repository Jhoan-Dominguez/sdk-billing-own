<#--
  Layout de todas las páginas de login del realm (login, crear cuenta, errores...).
  Izquierda: formulario. Derecha: información de la app (por ahora, README.md
  convertido a HTML al construir la imagen: info.ftl, ver docker/keycloak/Dockerfile).
  Basado en base/login/template.ftl de Keycloak 26.8: se conservan los scripts que
  necesita el flujo (sesión en otras pestañas, enlaces de un solo uso, menús).
-->
<#import "theme-resources.ftl" as themeResourceTags>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}">

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <meta name="color-scheme" content="light dark">
    <title>${msg("loginTitle")}</title>
    <link rel="icon" href="${url.resourcesPath}/img/favicon.svg" type="image/svg+xml" />
    <#if properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <script type="importmap">
        {
            "imports": {
                "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"
            }
        }
    </script>
    <script src="${url.resourcesPath}/js/menu-button-links.js" type="module"></script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="module">
        <#outputformat "JavaScript">
        import { startSessionPolling } from ${(url.resourcesPath + "/js/authChecker.js")?c};

        startSessionPolling(
            ${url.ssoLoginInOtherTabsUrl?c}
        );
        </#outputformat>
    </script>
    <script type="module">
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[data-once-link]");
            if (!link) {
                return;
            }
            if (link.getAttribute("aria-disabled") === "true") {
                event.preventDefault();
                return;
            }
            const { disabledClass } = link.dataset;
            if (disabledClass) {
                link.classList.add(...disabledClass.trim().split(/\s+/));
            }
            link.setAttribute("role", "link");
            link.setAttribute("aria-disabled", "true");
        });
    </script>
    <#if authenticationSession??>
        <script type="module">
            <#outputformat "JavaScript">
            import { checkAuthSession } from ${(url.resourcesPath + "/js/authChecker.js")?c};

            checkAuthSession(
                ${authenticationSession.authSessionIdHash?c}
            );
            </#outputformat>
        </script>
    </#if>
</head>

<body class="${properties.kcBodyClass!} ${bodyClass}" data-page-id="login-${pageId}">
<main class="cp-shell">
    <section class="cp-left">
        <div class="cp-card">
            <div class="cp-brand">
                <span class="cp-logo" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M6 2h12a1 1 0 0 1 1 1v18.2a.5.5 0 0 1-.8.4L16 20l-2 1.6a.5.5 0 0 1-.6 0L12 20.5l-1.4 1.1a.5.5 0 0 1-.6 0L8 20l-2.2 1.6a.5.5 0 0 1-.8-.4V3a1 1 0 0 1 1-1Zm2 5v2h8V7H8Zm0 4v2h8v-2H8Zm0 4v2h5v-2H8Z"/></svg>
                </span>
                <span class="cp-brand-name">${kcSanitize(msg("loginTitleHtml"))?no_esc}</span>
            </div>

            <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
                <h1 id="kc-page-title" class="cp-title"><#nested "header"></h1>
            <#else>
                <#nested "show-username">
                <div id="kc-username" class="cp-attempted">
                    <span id="kc-attempted-username">${auth.attemptedUsername}</span>
                    <a id="reset-login" href="${url.loginRestartFlowUrl}">${msg("restartLoginTooltip")}</a>
                </div>
            </#if>

            <#if displayRequiredFields>
                <p class="cp-required-note"><span class="required">*</span> ${msg("requiredFields")}</p>
            </#if>

            <#-- Las acciones iniciadas por la app no muestran avisos de "debes completar la acción". -->
            <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                <div class="${properties.kcAlertClass!} cp-alert-${message.type}" role="alert">
                    <span class="${properties.kcAlertTitleClass!}">${kcSanitize(message.summary)?no_esc}</span>
                </div>
            </#if>

            <#nested "form">

            <#if auth?has_content && auth.showTryAnotherWayLink()>
                <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                    <input type="hidden" name="tryAnotherWay" value="on"/>
                    <a href="#" id="try-another-way" class="cp-link"
                       onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
                </form>
            </#if>

            <#nested "socialProviders">

            <#if displayInfo>
                <div id="kc-info" class="cp-info">
                    <#nested "info">
                </div>
            </#if>
        </div>
    </section>

    <aside class="cp-right" aria-label="Información de la aplicación">
        <article id="cp-info" class="cp-markdown">
            <#include "info.ftl">
        </article>
    </aside>
</main>

</body>
</html>
</#macro>
