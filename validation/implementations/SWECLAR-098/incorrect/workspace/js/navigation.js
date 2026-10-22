document.querySelectorAll('.menu-button').forEach((button) => {
  const navigation = document.getElementById(button.getAttribute('aria-controls'));
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(open));
    navigation.dataset.open = String(open);
  });
});
