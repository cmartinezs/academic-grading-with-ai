Algoritmo RegistroGastos
	Definir opcion Como Entero
	Definir gasto, total Como Real
	total <- 0
	Repetir
		Escribir "1. Registrar gasto"
		Escribir "2. Ver total"
		Escribir "3. Salir"
		Leer opcion
		Segun opcion Hacer
			1:
				Escribir "Ingrese gasto"
				Leer gasto
				Si gasto > 0 Entonces
					total <- total + gasto
					Escribir "Gasto registrado"
				SiNo
					Escribir "Gasto invalido"
				FinSi
			2:
				Escribir "Total acumulado: ", total
			3:
				Escribir "Saliendo"
			De Otro Modo:
				Escribir "Opcion invalida"
		FinSegun
	Hasta Que opcion = 3
FinAlgoritmo
