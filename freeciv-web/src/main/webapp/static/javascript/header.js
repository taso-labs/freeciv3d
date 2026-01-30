$(document).ready(function () { 
	
	(function ($) {
		
		$(function () {
			loadStatistics();
		});
		
		function loadStatistics() {
			$.getJSON('/game/statistics', function(data) {
			    var ongoingGames = document.getElementById('ongoing-games');
			    if (data.ongoing > 0 && ongoingGames) {
				    ongoingGames.innerHTML = data.ongoing;
				}
				var singleplayer = document.getElementById('statistics-singleplayer');
				if (singleplayer) {
					singleplayer.innerHTML = data.finished.singlePlayer; //
				}
				var multiplayer = document.getElementById('statistics-multiplayer');
				if (multiplayer) {
					multiplayer.innerHTML = data.finished.multiPlayer; //
				}
			}).fail(function () {
				var statistics = document.getElementById('statistics');
				if (statistics) {
					statistics.style.display = 'none';
				}
				
			});
		}
	})($);

      $("#fcw-frontpage-nav-button").click(function(){
        $(".collapse.navbar-collapse").toggleClass("in");
      });

});