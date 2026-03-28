function func() {
    var rand = Math.floor(Math.random() * 1000);
    var location = 'https://english-games.ru/blendin.html' + rand;
    document.location.href = location
  }