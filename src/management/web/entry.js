'use strict';
(async () => {
    const token = location.hash.slice(1);
    if (!token) return;
    try {
        const response = await fetch('/manage/', {headers: {Authorization: 'Bearer ' + token}});
        if (!response.ok) {
            history.replaceState(null, '', location.pathname);
            return;
        }
        const page = await response.text();
        document.open();
        document.write(page);
        document.close();
    } catch {
        document.body.textContent = '无法连接管理服务，请检查服务后重新打开私密链接。';
    }
})();
